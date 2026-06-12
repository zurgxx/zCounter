from __future__ import annotations

from zcounter.models import QuotaSnapshot
from zcounter.providers.claude.provider import fetch_claude_quota
from zcounter.providers.codex.provider import fetch_codex_quotas
from zcounter.providers.cursor.provider import fetch_cursor_quota_if_configured


def fetch_all_quotas(*, user_initiated: bool = False) -> list[QuotaSnapshot]:
    snapshots = list(fetch_codex_quotas())
    cursor_snapshot = fetch_cursor_quota_if_configured()
    if cursor_snapshot is not None:
        snapshots.append(cursor_snapshot)
    snapshots.append(fetch_claude_quota(user_initiated=user_initiated))
    return snapshots
