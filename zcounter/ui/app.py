from __future__ import annotations

import threading
import tkinter as tk
from tkinter import font as tkfont

from zcounter.models import QuotaSnapshot, utc_now
from zcounter.providers.aggregate import fetch_all_quotas
from zcounter.ui.display import (
    EMAIL_WIDTH,
    REFRESH_SECONDS,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_STALE,
    account_key,
    display_primary,
    display_secondary,
    format_cursor_billing_reset,
    format_email,
    format_percent,
    format_reset_time,
    format_status_suffix,
    format_updated_footer,
    format_window_label,
    is_cursor,
    merge_with_cache,
    remaining_level,
)

REFRESH_MS = REFRESH_SECONDS * 1000
WINDOW_WIDTH = 540
ROW_HEIGHT = 18
HEADER_HEIGHT = 28
FOOTER_HEIGHT = 20
PADDING = 8

LEVEL_COLORS = {
    "normal": "#1a1a1a",
    "warning": "#b45309",
    "danger": "#b91c1c",
}
STATUS_COLORS = {
    STATUS_OK: "#4b5563",
    STATUS_STALE: "#6b7280",
    STATUS_ERROR: "#b91c1c",
}


class QuotaUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("zCounter")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)

        self._cache: dict[str, QuotaSnapshot] = {}
        self._status_by_key: dict[str, str] = {}
        self._fetching = False
        self._last_refresh_at = utc_now()

        mono = tkfont.Font(family="DejaVu Sans Mono", size=9)
        if mono.actual("family") == "TkFixedFont":
            mono = tkfont.Font(family="TkFixedFont", size=9)
        self._mono = mono

        self._header = tk.Label(
            root,
            text="zCounter  quotas",
            font=("TkDefaultFont", 9, "bold"),
            anchor="w",
        )
        self._rows_frame = tk.Frame(root)
        self._footer = tk.Label(
            root,
            text="loading…",
            font=("TkDefaultFont", 8),
            fg="#6b7280",
            anchor="w",
        )

        self._header.pack(fill="x", padx=PADDING, pady=(PADDING, 2))
        self._rows_frame.pack(fill="x", padx=PADDING)
        self._footer.pack(fill="x", padx=PADDING, pady=(2, PADDING))

        self.root.after(0, self._schedule_refresh)
        self.root.after(REFRESH_MS, self._tick)

    def _tick(self) -> None:
        self._schedule_refresh()
        self.root.after(REFRESH_MS, self._tick)

    def _schedule_refresh(self) -> None:
        if self._fetching:
            return
        self._fetching = True
        thread = threading.Thread(target=self._fetch_worker, daemon=True)
        thread.start()

    def _fetch_worker(self) -> None:
        try:
            snapshots = fetch_all_quotas()
        except Exception:
            self.root.after(0, self._apply_fetch_failure)
            return
        self.root.after(0, lambda: self._apply_snapshots(snapshots))

    def _apply_fetch_failure(self) -> None:
        self._fetching = False
        if not self._cache:
            self._render_rows([])
            self._footer.configure(text="fetch failed  ·  refresh 60s")
            return
        merged = [
            (snapshot, STATUS_STALE)
            for snapshot in self._cache.values()
        ]
        self._last_refresh_at = utc_now()
        self._render_rows(merged)
        self._footer.configure(
            text=f"fetch failed  ·  {format_updated_footer(self._last_refresh_at)}",
        )

    def _apply_snapshots(self, snapshots: list[QuotaSnapshot]) -> None:
        self._fetching = False
        merged: list[tuple[QuotaSnapshot, str]] = []
        for snapshot in snapshots:
            key = account_key(snapshot)
            cached = self._cache.get(key)
            merged_snapshot, status = merge_with_cache(cached, snapshot)
            if status == STATUS_OK:
                self._cache[key] = merged_snapshot
            elif status == STATUS_STALE:
                self._cache[key] = merged_snapshot
            self._status_by_key[key] = status
            merged.append((merged_snapshot, status))

        self._last_refresh_at = utc_now()
        self._render_rows(merged)
        self._footer.configure(text=format_updated_footer(self._last_refresh_at))

    def _render_rows(self, rows: list[tuple[QuotaSnapshot, str]]) -> None:
        for child in self._rows_frame.winfo_children():
            child.destroy()

        if not rows:
            empty = tk.Label(
                self._rows_frame,
                text="no accounts",
                font=self._mono,
                fg="#6b7280",
                anchor="w",
            )
            empty.pack(fill="x")
            height = HEADER_HEIGHT + ROW_HEIGHT + FOOTER_HEIGHT + PADDING * 2
            self.root.geometry(f"{WINDOW_WIDTH}x{height}")
            return

        for snapshot, status in rows:
            self._add_row(snapshot, status)

        body_height = len(rows) * ROW_HEIGHT
        height = HEADER_HEIGHT + body_height + FOOTER_HEIGHT + PADDING * 2
        self.root.geometry(f"{WINDOW_WIDTH}x{height}")

    def _add_row(self, snapshot: QuotaSnapshot, status: str) -> None:
        if is_cursor(snapshot):
            self._add_cursor_row(snapshot, status)
        else:
            self._add_codex_row(snapshot, status)

    def _add_email_label(self, row: tk.Frame, snapshot: QuotaSnapshot) -> None:
        email_label = tk.Label(
            row,
            text=format_email(snapshot.email, width=EMAIL_WIDTH),
            font=self._mono,
            fg="#1a1a1a",
            anchor="w",
            width=EMAIL_WIDTH,
        )
        email_label.pack(side="left")

    def _add_cursor_row(self, snapshot: QuotaSnapshot, status: str) -> None:
        row = tk.Frame(self._rows_frame)
        row.pack(fill="x", pady=0)
        self._add_email_label(row, snapshot)

        primary = display_primary(snapshot)
        secondary = display_secondary(snapshot)

        total_label = tk.Label(
            row,
            text=f"Total {format_percent(primary)} ",
            font=self._mono,
            fg=LEVEL_COLORS[remaining_level(primary)],
            anchor="w",
        )
        total_label.pack(side="left")

        auto_label = tk.Label(
            row,
            text=f"Auto {format_percent(secondary)} ",
            font=self._mono,
            fg=LEVEL_COLORS[remaining_level(secondary)],
            anchor="w",
        )
        auto_label.pack(side="left")

        reset_label = tk.Label(
            row,
            text=format_cursor_billing_reset(
                primary.reset_at if primary is not None else None,
            ),
            font=self._mono,
            fg="#4b5563",
            anchor="w",
            width=16,
        )
        reset_label.pack(side="left")

        suffix = format_status_suffix(status, snapshot)
        if suffix:
            tail_label = tk.Label(
                row,
                text=f"  {suffix}",
                font=self._mono,
                fg=STATUS_COLORS.get(status, "#4b5563"),
                anchor="w",
            )
            tail_label.pack(side="left")

    def _add_codex_row(self, snapshot: QuotaSnapshot, status: str) -> None:
        row = tk.Frame(self._rows_frame)
        row.pack(fill="x", pady=0)
        self._add_email_label(row, snapshot)

        primary = display_primary(snapshot)
        secondary = display_secondary(snapshot)
        primary_label = format_window_label(snapshot.primary_label, "P")
        secondary_label = format_window_label(snapshot.secondary_label, "S")

        primary_label_widget = tk.Label(
            row,
            text=f"{primary_label} {format_percent(primary):>3} ",
            font=self._mono,
            fg=LEVEL_COLORS[remaining_level(primary)],
            anchor="w",
        )
        primary_label_widget.pack(side="left")

        primary_reset_label = tk.Label(
            row,
            text=format_reset_time(primary),
            font=self._mono,
            fg="#4b5563",
            anchor="w",
        )
        primary_reset_label.pack(side="left")

        secondary_label_widget = tk.Label(
            row,
            text=f"  {secondary_label} {format_percent(secondary):>3} ",
            font=self._mono,
            fg=LEVEL_COLORS[remaining_level(secondary)],
            anchor="w",
        )
        secondary_label_widget.pack(side="left")

        secondary_reset_label = tk.Label(
            row,
            text=format_reset_time(secondary),
            font=self._mono,
            fg="#4b5563",
            anchor="w",
        )
        secondary_reset_label.pack(side="left")

        suffix = format_status_suffix(status, snapshot)
        if suffix:
            tail_label = tk.Label(
                row,
                text=f"  {suffix}",
                font=self._mono,
                fg=STATUS_COLORS.get(status, "#4b5563"),
                anchor="w",
            )
            tail_label.pack(side="left")


def run() -> None:
    root = tk.Tk()
    QuotaUI(root)
    root.mainloop()
