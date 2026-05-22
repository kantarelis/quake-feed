# Vault — secret layout & API-key lifecycle

Vault runs as a **dev-mode container** in the local `docker-compose` stack.
This document covers (a) how it's wired into the app, (b) where API-key
material lives, and (c) the issuance / revoke lifecycle.

> **Dev-mode warning.** Dev-mode Vault keeps everything in memory and starts
> unsealed with a known root token. Fine for this local-only project; not
> what you'd use in production.

## Wiring

- **Address:** `http://vault:8200` (in-container) / `http://localhost:8200`
  (host).
- **Token:** dev root token from `${VAULT_DEV_ROOT_TOKEN_ID}` (`.env`).
- **Mount:** `secret/` — KV v2, the dev-mode default.
- **Client:** `functions/vault.py` (`VaultClient`); constructed at app boot
  via `functions/vault.py::init_vault`.

## API-key path layout

```
secret/
└── api-keys/
    ├── 1            ← {raw_key, label, issued_at}
    ├── 2            ← {raw_key, label, issued_at}
    └── …            ← one path per row in quake.api_keys
```

- **One path per key.** Path = `secret/api-keys/<key_id>` where `<key_id>`
  is the `id` column of the `quake.api_keys` row created at issuance time.
- **Payload fields.** `raw_key` (the `qkf_<hex32>` value sent on the wire),
  `label` (operator-supplied tag, optional), `issued_at` (ISO-8601 UTC).
- **No hash in Vault.** The hash is the DB's index column; Vault holds only
  the raw value.

## Issuance — `make issue-api-key`

```
make issue-api-key LABEL=alice SCOPES=admin
```

1. Generate `raw = "qkf_" + secrets.token_hex(16)`.
2. `hash = sha256(raw).hexdigest()`.
3. `INSERT INTO quake.api_keys(key_hash, label, scopes) RETURNING id`.
4. `vault.put_secret("api-keys/<id>", {raw_key, label, issued_at})`.
5. Print `raw` once. **It cannot be recovered.**

If step 4 fails, step 3 is rolled back so a hash never lives in the DB
without a matching Vault entry.

## Revoke — `make revoke-api-key`

```
make revoke-api-key KEY_ID=42
```

1. `UPDATE quake.api_keys SET revoked_at = now() WHERE id = 42 AND revoked_at IS NULL`.
2. `vault.delete_secret("api-keys/42")` + destroy versions so the raw
   value is unrecoverable.

Revoke is idempotent — calling it a second time is a no-op.

## Listing & pruning

```
make list-api-keys      # id, label, scopes, status — never the raw key
make prune-api-keys     # hard-delete every revoked key (cascades to its filters)
```

`list-api-keys` reads `quake.api_keys` for an at-a-glance inventory; it never
touches Vault and never prints raw key material. `prune-api-keys` permanently
deletes the rows of already-**revoked** keys (their `quake.alert_filters`
cascade away); active keys are left untouched. Revoke first, prune later.

## Authentication resolution

`quake/api/auth.py::Authenticate` resolves a request like so:

```
              Authorization: Bearer qkf_<hex32>
                          │
                          ▼
                  hash = sha256(raw)
                          │
                          ▼
       DB: SELECT * FROM quake.api_keys
           WHERE key_hash = hash
                          │
              ┌───────────┴────────────┐
              │                        │
          no row → 401             row found
                                       │
                                       ▼
              row.revoked_at IS NOT NULL → 401
                                       │
                                       ▼
              Vault: GET secret/api-keys/<row.id>
                                       │
              ┌───────────┬────────────┘
              │           │
       no entry → 401   raw mismatch → 401
                          │
                          ▼
              required_scope ∉ row.scopes → 403
                          │
                          ▼
       touch last_seen_at, return ApiKeyRow
```

Both DB and Vault must be intact for a key to validate. A DB-only or
Vault-only compromise is not enough to forge a working key.

## Operator notes

- **Unseal after restart.** Even dev-mode loses its in-memory state on
  container restart. `make vault-unseal` recovers it from the printed
  unseal key.
- **Raw keys leak only via stdout.** No log line, no audit row, no metric
  carries the raw value. The Vault audit log (if enabled) records the
  writes.

## Related

- [`docs/architecture.md`](architecture.md) — where the `Authenticate` gate sits in the request flow.
- [`docs/frontend.md`](frontend.md) — how the SPA stores and sends the issued key.
