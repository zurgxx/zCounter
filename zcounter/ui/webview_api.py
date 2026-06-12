from __future__ import annotations

import threading
from typing import Any

from zcounter.models import utc_now
from zcounter.providers.aggregate import fetch_all_quotas
from zcounter.ui.viewmodel import SnapshotStore, build_payload


class WebviewAPI:
    def __init__(self) -> None:
        self._store = SnapshotStore()
        self._lock = threading.Lock()

    def refresh(self, user_initiated: bool = False) -> dict[str, Any]:
        if not self._lock.acquire(blocking=False):
            return {"busy": True}
        try:
            try:
                rows = self._store.merge(fetch_all_quotas(user_initiated=user_initiated))
            except Exception:
                rows = self._store.stale_rows()
            payload = build_payload(rows, utc_now())
            payload["busy"] = False
            return payload
        finally:
            self._lock.release()
