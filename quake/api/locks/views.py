"""Views for the ``/admin/locks`` endpoint group.

Lock rows are seeded by the baseline migration; this surface only
flips ``is_locked`` and updates the metadata columns. Unknown
``lock_name`` values resolve to 404 — there is no auto-create.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, status

from database.etls.endpoint_locks import EndpointLocksETL
from quake.api.locks.models import LockResponse, LocksListResponse, SetLockRequest


class LocksManagerViews:
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    async def list_locks(self) -> LocksListResponse:
        rows = EndpointLocksETL().list_all()
        return LocksListResponse(
            count=len(rows),
            locks=[LockResponse.model_validate(r) for r in rows],
        )

    async def set_lock(self, lock_name: str, body: SetLockRequest) -> LockResponse:
        row = EndpointLocksETL().set_lock(
            lock_name,
            locked_by=body.locked_by,
            reason=body.reason,
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"no such lock: {lock_name}",
            )
        return LockResponse.model_validate(row)

    async def clear_lock(self, lock_name: str) -> LockResponse:
        row = EndpointLocksETL().clear_lock(lock_name)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"no such lock: {lock_name}",
            )
        return LockResponse.model_validate(row)
