from __future__ import annotations

import threading
import tkinter as tk
from tkinter import font as tkfont

from zcounter.models import QuotaSnapshot, isoformat_or_none, utc_now
from zcounter.providers.codex.provider import fetch_codex_quotas
from zcounter.ui.display import (
    STATUS_ERROR,
    STATUS_OK,
    STATUS_STALE,
    account_key,
    format_email,
    format_percent,
    format_reset_hint,
    format_status_suffix,
    merge_with_cache,
    remaining_level,
)

REFRESH_MS = 60_000
WINDOW_WIDTH = 520
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
        self._last_refresh: str = "-"

        mono = tkfont.Font(family="DejaVu Sans Mono", size=9)
        if mono.actual("family") == "TkFixedFont":
            mono = tkfont.Font(family="TkFixedFont", size=9)
        self._mono = mono

        self._header = tk.Label(
            root,
            text="zCounter  Codex quotas",
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
            snapshots = fetch_codex_quotas()
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
        self._last_refresh = isoformat_or_none(utc_now()) or "-"
        self._render_rows(merged)
        self._footer.configure(text=f"fetch failed  ·  updated {self._last_refresh}  ·  refresh 60s")

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

        self._last_refresh = isoformat_or_none(utc_now()) or "-"
        self._render_rows(merged)
        self._footer.configure(text=f"updated {self._last_refresh}  ·  refresh 60s")

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
        row = tk.Frame(self._rows_frame)
        row.pack(fill="x", pady=0)

        email_label = tk.Label(
            row,
            text=format_email(snapshot.email),
            font=self._mono,
            fg="#1a1a1a",
            anchor="w",
            width=30,
        )
        email_label.pack(side="left")

        five_label = tk.Label(
            row,
            text=f"5H {format_percent(snapshot.five_hour):>4}",
            font=self._mono,
            fg=LEVEL_COLORS[remaining_level(snapshot.five_hour)],
            anchor="w",
            width=9,
        )
        five_label.pack(side="left")

        weekly_label = tk.Label(
            row,
            text=f"WK {format_percent(snapshot.weekly):>4}",
            font=self._mono,
            fg=LEVEL_COLORS[remaining_level(snapshot.weekly)],
            anchor="w",
            width=9,
        )
        weekly_label.pack(side="left")

        hint = format_reset_hint(snapshot)
        suffix = format_status_suffix(status, snapshot)
        if status == STATUS_OK:
            tail = hint
        elif status == STATUS_STALE:
            tail = f"{hint}  stale" if hint != "-" else "stale"
        else:
            tail = suffix or hint
        tail_color = STATUS_COLORS.get(status, "#4b5563")
        tail_label = tk.Label(
            row,
            text=tail,
            font=self._mono,
            fg=tail_color,
            anchor="w",
        )
        tail_label.pack(side="left", fill="x", expand=True)


def run() -> None:
    root = tk.Tk()
    QuotaUI(root)
    root.mainloop()
