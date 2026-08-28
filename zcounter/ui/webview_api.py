from __future__ import annotations

import logging
import threading
from typing import Any

from zcounter.models import utc_now
from zcounter.providers.aggregate import fetch_all_quotas
from zcounter.ui.usage_log import append_usage_log
from zcounter.ui.viewmodel import SnapshotStore, build_payload


logger = logging.getLogger(__name__)


class WebviewAPI:
    def __init__(self) -> None:
        self._store = SnapshotStore()
        self._lock = threading.Lock()

    def refresh(self, user_initiated: bool = False) -> dict[str, Any]:
        if not self._lock.acquire(blocking=False):
            return {"busy": True}
        try:
            snapshots_for_log = None
            try:
                fresh_snapshots = fetch_all_quotas(user_initiated=user_initiated)
                rows = self._store.merge(fresh_snapshots)
                snapshots_for_log = fresh_snapshots
            except Exception:
                rows = self._store.stale_rows()
            updated_at = utc_now()
            payload = build_payload(rows, updated_at)
            if snapshots_for_log is not None:
                try:
                    append_usage_log(snapshots_for_log, updated_at)
                except Exception:
                    # Usage history is best effort and must never affect refresh/UI.
                    logger.warning("failed to append usage log", exc_info=True)
            payload["busy"] = False
            return payload
        finally:
            self._lock.release()
