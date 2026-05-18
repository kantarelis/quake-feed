"""Manager for the ``/admin/locks`` endpoint group.

Admin scope (``Authenticate(required_scope="admin")``) is declared at
the router level so every route inherits it without per-route
repetition.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from quake.api.auth import Authenticate
from quake.api.locks.views import LocksManagerViews


class LocksManager:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger if logger else logging.getLogger("LocksManager")
        self.router = APIRouter(
            prefix="/admin/locks",
            dependencies=[Depends(Authenticate(required_scope="admin"))],
        )
        self.views = LocksManagerViews(logger=self.logger)

    def run(self) -> APIRouter:
        self.router.add_api_route(
            "",
            endpoint=self.views.list_locks,
            methods=["GET"],
            summary="List all endpoint locks",
            description="Return every row in quake.endpoint_locks.",
            operation_id="admin_locks_list",
            tags=["Admin"],
        )
        self.router.add_api_route(
            "/{lock_name}",
            endpoint=self.views.set_lock,
            methods=["POST"],
            summary="Set an endpoint lock",
            description="Flip is_locked=true on a seeded lock_name. Body carries optional locked_by/reason.",
            operation_id="admin_locks_set",
            tags=["Admin"],
        )
        self.router.add_api_route(
            "/{lock_name}",
            endpoint=self.views.clear_lock,
            methods=["DELETE"],
            summary="Clear an endpoint lock",
            description="Flip is_locked=false and null out locked_by / locked_at / reason.",
            operation_id="admin_locks_clear",
            tags=["Admin"],
        )
        return self.router
