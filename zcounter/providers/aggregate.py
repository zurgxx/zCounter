from __future__ import annotations

from zcounter.models import QuotaSnapshot
from zcounter.providers.codex.provider import fetch_codex_quotas
from zcounter.providers.cursor.provider import fetch_cursor_quota_if_configured


def fetch_all_quotas() -> list[QuotaSnapshot]:
    snapshots = list(fetch_codex_quotas())
    cursor_snapshot = fetch_cursor_quota_if_configured()
    if cursor_snapshot is not None:
        snapshots.append(cursor_snapshot)
    return snapshots
