"""Thin HashiCorp Vault client wrapper.

Vault runs as a dev-mode container in the local docker-compose stack. This
module provides a small typed surface for the rest of the app: get/put/list
secrets, plus a startup helper that verifies the dev container is reachable
and unsealed.
"""

from __future__ import annotations

import logging

import hvac
from hvac.exceptions import InvalidPath, VaultError

from functions.environment import VaultConfig, get_environmental_variables


class VaultClient:
    """Typed wrapper around hvac for the KV v2 secret engine at mount ``secret``."""

    KV_MOUNT = "secret"

    def __init__(self, address: str, token: str) -> None:
        self._client = hvac.Client(url=address, token=token)

    @property
    def raw(self) -> hvac.Client:
        return self._client

    def get_secret(self, path: str, key: str) -> str | None:
        try:
            resp = self._client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point=self.KV_MOUNT,
                raise_on_deleted_version=True,
            )
        except InvalidPath:
            return None
        data = resp.get("data", {}).get("data", {})
        value = data.get(key)
        return str(value) if value is not None else None

    def put_secret(self, path: str, payload: dict[str, str]) -> None:
        self._client.secrets.kv.v2.create_or_update_secret(
            path=path,
            secret=payload,
            mount_point=self.KV_MOUNT,
        )

    def list_keys(self, path: str) -> list[str]:
        try:
            resp = self._client.secrets.kv.v2.list_secrets(
                path=path,
                mount_point=self.KV_MOUNT,
            )
        except InvalidPath:
            return []
        keys = resp.get("data", {}).get("keys", [])
        return [str(k) for k in keys]


def init_vault(logger: logging.Logger) -> VaultClient:
    """Construct a VaultClient and warn loudly if the server is not ready.

    Returning the client even when Vault is not ready lets the caller decide
    whether to fail fast or retry; logging makes the cause visible.
    """
    cfg: VaultConfig = get_environmental_variables().vault
    token = cfg.token or cfg.dev_root_token_id
    client = VaultClient(address=cfg.address, token=token)

    try:
        if not client.raw.sys.is_initialized():
            logger.warning("Vault is not initialized; run `make vault-init` first.")
        elif client.raw.sys.is_sealed():
            logger.warning("Vault is sealed; run `make vault-unseal` to open it.")
        else:
            logger.info("Vault is reachable and unsealed.", extra={"vault_address": cfg.address})
    except (VaultError, ConnectionError, OSError) as exc:
        logger.warning(
            "Vault status check failed; continuing without verification.",
            extra={"vault_address": cfg.address, "error": str(exc)},
        )

    return client
