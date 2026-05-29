from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from zcounter.models import QuotaSnapshot
from zcounter.providers.codex.provider import fetch_codex_quotas


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show Codex quota usage.")
    parser.add_argument("--json", action="store_true", help="output normalized JSON")
    args = parser.parse_args(argv)

    snapshots = fetch_codex_quotas()
    if args.json:
        print(json.dumps([snapshot.to_json() for snapshot in snapshots], ensure_ascii=False, indent=2))
        return 0

    print_table(snapshots)
    return 0


def print_table(snapshots: Sequence[QuotaSnapshot]) -> None:
    rows = [_row(snapshot) for snapshot in snapshots]
    headers = ["ACCOUNT", "PLAN", "5H REM", "5H USED", "WEEKLY REM", "WEEKLY USED", "SOURCE", "ERROR"]
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    print(_format_row(headers, widths))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print(_format_row(row, widths))


def _row(snapshot: QuotaSnapshot) -> list[str]:
    return [
        snapshot.email or "-",
        _title_plan(snapshot.plan),
        _remaining(snapshot.five_hour),
        _used(snapshot.five_hour),
        _remaining(snapshot.weekly),
        _used(snapshot.weekly),
        snapshot.source,
        snapshot.error or "-",
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


def _used(window) -> str:
    if window is None:
        return "-"
    return f"{window.used_percent:.0f}%"


if __name__ == "__main__":
    raise SystemExit(main())

