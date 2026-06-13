# Enterprise Auth Guide

Axon Phase 4 ships a full API key management system with role-based access control (RBAC)
and an append-only audit log. This guide covers how to manage keys, what each role can do,
how to rotate keys safely, and how to read the audit log.

---

## API Key Management Workflow

### How keys work

Every Axon API key is a 42-character token in the format:

```
axon_live_<32 hex characters>
```

Example: `axon_live_a3f8c2d1e4b5f6a7b8c9d0e1f2a3b4c5`

When a key is created, the **raw key is returned exactly once** in the API response. Axon
stores only a bcrypt hash of the key — the raw value is never persisted. If a key is lost,
it must be rotated (revoked and replaced).

### Creating a key

```bash
curl -X POST https://axon.internal.example.com/v1/auth/keys \
  -H "X-Axon-API-Key: $AXON_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "ci-pipeline-prod",
    "role": "engineer",
    "expires_in_days": 90
  }'
```

Response (HTTP 201):

```json
{
  "key_prefix": "axon_liv",
  "name": "ci-pipeline-prod",
  "role": "engineer",
  "raw_key": "axon_live_a3f8c2d1e4b5f6a7b8c9d0e1f2a3b4c5",
  "created_at": "2024-11-01T12:00:00Z",
  "expires_at": "2025-01-30T12:00:00Z"
}
```

Store `raw_key` immediately in your secrets manager. It will not be shown again.

### Listing keys

```bash
curl https://axon.internal.example.com/v1/auth/keys \
  -H "X-Axon-API-Key: $AXON_ADMIN_KEY"
```

The response lists all non-revoked keys with their prefix, name, role, `created_at`,
`last_used_at`, and `expires_at`. **The response never includes `key_hash` or raw key values.**

### Revoking a key

```bash
curl -X DELETE https://axon.internal.example.com/v1/auth/keys/axon_liv \
  -H "X-Axon-API-Key: $AXON_ADMIN_KEY"
```

Returns HTTP 204 on success. The key is immediately invalid. Returns HTTP 404 if the prefix
is not found. All revocations are recorded in the audit log.

---

## Roles and Permissions

Axon uses three roles in a strict hierarchy: `viewer < engineer < admin`.

### viewer

Read-only access to observability data.

| Endpoint | Access |
|---|---|
| `GET /v1/attribution` | ✓ |
| `GET /v1/spans` | ✓ |
| `GET /v1/budgets` | ✓ |
| `GET /v1/health` | ✓ |
| `POST /v1/budgets` | ✗ |
| `DELETE /v1/budgets/{tag}` | ✗ |
| `POST /v1/auth/keys` | ✗ |
| `GET /v1/auth/keys` | ✗ |
| `DELETE /v1/auth/keys/{prefix}` | ✗ |
| `GET /v1/audit` | ✗ |

Assign `viewer` keys to the Axon dashboard in environments where the JS bundle is accessible
to untrusted users, or to read-only monitoring integrations.

### engineer

Read access plus the ability to manage budgets and submit spans.

| Endpoint | Access |
|---|---|
| Everything `viewer` can access | ✓ |
| `POST /v1/spans` | ✓ |
| `POST /v1/budgets` | ✓ |
| `PUT /v1/budgets/{tag}` | ✓ |
| `DELETE /v1/budgets/{tag}` | ✓ |
| `POST /v1/auth/keys` | ✗ |
| `GET /v1/auth/keys` | ✗ |
| `GET /v1/audit` | ✗ |

Assign `engineer` keys to CI pipelines, the Axon SDK backend client, and application services
that need to write spans and manage budgets.

### admin

Full access including key management and audit log.

| Endpoint | Access |
|---|---|
| Everything `engineer` can access | ✓ |
| `POST /v1/auth/keys` | ✓ |
| `GET /v1/auth/keys` | ✓ |
| `DELETE /v1/auth/keys/{prefix}` | ✓ |
| `GET /v1/audit` | ✓ |

Admin keys should be held only by platform team operators and protected in a secrets manager.
Rotate admin keys on a 30-day schedule or immediately after any suspected compromise.

---

## Key Rotation Procedure

Rotation is a three-step process: create a replacement, update consumers, revoke the old key.

### Step 1 — Create a replacement key

```bash
curl -X POST https://axon.internal.example.com/v1/auth/keys \
  -H "X-Axon-API-Key: $AXON_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "ci-pipeline-prod-v2",
    "role": "engineer",
    "expires_in_days": 90
  }'
```

Save the `raw_key` from the response into your secrets manager under a new version.

### Step 2 — Update consumers

Update every service, CI job, and integration that uses the old key to reference the new
secret version. Verify each consumer is working correctly with the new key before proceeding.

```bash
# Verify the new key works
curl https://axon.internal.example.com/v1/health \
  -H "X-Axon-API-Key: $NEW_KEY"
```

### Step 3 — Revoke the old key

Once all consumers have been migrated, revoke the old key by its prefix:

```bash
curl -X DELETE https://axon.internal.example.com/v1/auth/keys/<old_prefix> \
  -H "X-Axon-API-Key: $AXON_ADMIN_KEY"
```

Verify revocation by confirming the old key returns HTTP 401.

### Emergency rotation

If a key is believed to be compromised:
1. Revoke immediately (`DELETE /v1/auth/keys/{prefix}`) — no waiting.
2. Check the audit log for actions taken with that key prefix in the past 24 hours.
3. Create a replacement key and deploy it.

---

## Audit Log

### Accessing the audit log

```bash
curl "https://axon.internal.example.com/v1/audit?limit=100" \
  -H "X-Axon-API-Key: $AXON_ADMIN_KEY"
```

Query parameters:

| Parameter | Type | Description |
|---|---|---|
| `from_ts` | ISO 8601 | Filter entries at or after this timestamp |
| `to_ts` | ISO 8601 | Filter entries at or before this timestamp |
| `actor_prefix` | string | Filter by the key prefix that performed the action |
| `action` | string | Filter by action type (e.g., `create_key`, `revoke_key`) |
| `limit` | integer | Max entries to return (default 100, max 1000) |

### Interpreting entries

Each audit log entry has the following fields:

| Field | Description |
|---|---|
| `id` | UUID of the log entry |
| `timestamp` | UTC timestamp of the action |
| `actor_key_prefix` | First 8 characters of the key that performed the action |
| `action` | What happened (`create_key`, `revoke_key`, `list_keys`, `read_audit`) |
| `resource` | The object affected (e.g., key prefix, or `audit_log`) |
| `result` | `success`, `denied`, or `error` |
| `ip_address` | Remote IP of the request (IPv4 or IPv6, max 45 chars) |
| `details` | JSON object with additional context (role granted, key name, etc.) |

### Common queries

**Who created keys in the last 7 days?**
```bash
curl "https://axon.internal.example.com/v1/audit?action=create_key&from_ts=2024-10-25T00:00:00Z" \
  -H "X-Axon-API-Key: $AXON_ADMIN_KEY"
```

**All actions by a specific key:**
```bash
curl "https://axon.internal.example.com/v1/audit?actor_prefix=axon_liv" \
  -H "X-Axon-API-Key: $AXON_ADMIN_KEY"
```

**Failed authorization attempts:**
```bash
curl "https://axon.internal.example.com/v1/audit?result=denied" \
  -H "X-Axon-API-Key: $AXON_ADMIN_KEY"
```

The audit log is append-only. There is no API to delete or modify entries.

---

## Backward Compatibility: Environment Variable Key

Axon Phases 1–3 used a single `AXON_API_KEY` environment variable to authenticate all
requests to the backend. This mechanism is fully supported in Phase 4.

If a request arrives with a raw key that matches `settings.api_key` (the `AXON_API_KEY`
environment variable), it is treated as an `admin`-role key without a database lookup. No
`APIKeyRecord` is required in the database.

This means:
- Existing deployments continue to work with no changes.
- The env-var key always has admin privileges and never expires.
- It does not appear in `GET /v1/auth/keys` (it is not stored in the database).
- Actions performed with the env-var key are recorded in the audit log with
  `actor_key_prefix = "env_key"`.

**Recommendation for production:** Create a named admin key, store it in your secrets manager,
and remove `AXON_API_KEY` from the environment once all services have been migrated. This
gives you full audit trail coverage and expiry control.
