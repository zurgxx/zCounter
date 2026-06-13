from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from zcounter.models import QuotaSnapshot
from zcounter.providers.aggregate import fetch_all_quotas


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show quota usage.")
    parser.add_argument("--json", action="store_true", help="output normalized JSON")
    args = parser.parse_args(argv)

    snapshots = fetch_all_quotas()
    if args.json:
        print(json.dumps([snapshot.to_json() for snapshot in snapshots], ensure_ascii=False, indent=2))
        return 0

    print_table(snapshots)
    return 0


def print_table(snapshots: Sequence[QuotaSnapshot]) -> None:
    rows = [_row(snapshot) for snapshot in snapshots]
    headers = [
        "PROVIDER",
        "ACCOUNT",
        "PLAN",
        "PRIMARY",
        "USED",
        "SECONDARY",
        "USED",
        "TERTIARY",
        "USED",
        "SOURCE",
        "ERROR",
    ]
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    print(_format_row(headers, widths))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print(_format_row(row, widths))


def _row(snapshot: QuotaSnapshot) -> list[str]:
    primary = snapshot.primary or snapshot.five_hour
    secondary = snapshot.secondary or snapshot.weekly
    tertiary = snapshot.tertiary
    return [
        snapshot.provider,
        snapshot.email or "-",
        _title_plan(snapshot.plan),
        _labeled_remaining(snapshot.primary_label, primary),
        _used(primary),
        _labeled_remaining(snapshot.secondary_label, secondary),
        _used(secondary),
        _labeled_remaining(snapshot.tertiary_label, tertiary),
        _used(tertiary),
        snapshot.source,
        snapshot.error or _warning(snapshot) or "-",
    ]


def _format_row(values: Sequence[str], widths: Sequence[int]) -> str:
    return "  ".join(value.ljust(widths[index]) for index, value in enumerate(values))


def _title_plan(plan: str | None) -> str:
    if not plan:
        return "-"
    return plan[:1].upper() + plan[1:]


def _remaining(window) -> str:
    if window is None:
        return "-"
    return f"{window.remaining_percent:.0f}%"


def _labeled_remaining(label: str | None, window) -> str:
    if window is None:
        return "-"
    return f"{label or '-'} {window.remaining_percent:.0f}%"


def _used(window) -> str:
    if window is None:
        return "-"
    return f"{window.used_percent:.0f}%"


def _warning(snapshot: QuotaSnapshot) -> str | None:
    if not snapshot.warnings:
        return None
    return snapshot.warnings[0]


if __name__ == "__main__":
    raise SystemExit(main())
