# Authentication

> How requests to the Runtime are authenticated: self-hosted Logto (OIDC)
> issues per-user JWTs; AgentOS verifies them locally against an exported
> JWKS file. Decision rationale: [ADR 0009](../adr/0009-idp-logto-self-hosted.md).
> Implemented in v0.6.0 ([plan](../plan/v0.6.0-user-authentication.md)).

---

## 1. Request Path

```
Browser SPA (Web Client)                     Logto (docker, :3001/:3002)
┌─────────────────────────┐                  ┌───────────────────────────┐
│ @logto/react SDK        │  auth code+PKCE  │ sign-in page, OIDC issuer │
│ LogtoProvider           │ ───────────────> │ http://<host>:3001/oidc   │
│ getAccessToken(resource)│ <─────────────── │ signs ES384 JWT           │
└──────────┬──────────────┘   JWT access     └─────────────▲─────────────┘
           │                token (aud = API resource)     │ shares PostgreSQL
           │ Authorization: Bearer <jwt>                   │ (own database)
           ▼                                               │
┌──────────────────────────────────────────────────────────┴────────────┐
│ Runtime (AgentOS, :7777)                                              │
│  JWTMiddleware: verify signature (JWT_JWKS_FILE) + iss + aud          │
│  Authorization providers (OR):                                        │
│    ScopeAuthorizationProvider  — admin-scope dev/service tokens       │
│    AnyAuthenticatedProvider    — any verified token passes            │
│  UserDirectory (user_directory=True): JIT roster, disabled kill switch│
└───────────────────────────────────────────────────────────────────────┘
```

- Every HTTP route requires a verified Bearer JWT except `/health` and the
  docs endpoints. No token or an invalid token → 401; a valid token from a
  **disabled** user → 403.
- All authenticated users have identical permissions (no roles in this
  phase). [Per-user data isolation](data-isolation.md) scopes framework data
  to the JWT subject; the directory built here is its foundation.
- `sub` of the JWT is the AgentOS `user_id`. On a subject's first request
  the UserDirectory auto-provisions a roster row
  (`ai.agno_authz_users` in the Runtime database). Disabling a user
  (Console deletion does **not** do this — use the roster) revokes access
  even while their token is still valid.

## 2. Token Contract

| Claim | Value | Checked by Runtime |
|-------|-------|--------------------|
| `iss` | `$LOGTO_ENDPOINT/oidc` (e.g. `http://localhost:3001/oidc`) | yes (`JWT_ISSUER`) |
| `aud` | API resource URI, `https://spectres.runtime/api` | yes (`JWT_AUDIENCE`) |
| `sub` | Logto user id (or M2M app id) | identity |
| `exp`/`iat` | 1 h lifetime; SDK refreshes via refresh token | yes (signature validation) |
| signature | ES384, OIDC signing key | yes (`JWT_JWKS_FILE`) |

Logto only mints a **JWT** access token when the client requests the API
resource indicator; without it the token is opaque and the Runtime rejects
it. The Web Client requests the resource via `VITE_LOGTO_API_RESOURCE`.
Logto's `scope` claim is not evaluated in this phase (authorization is
authentication-only).

## 3. Configuration

Runtime (`.env`, see `.env.example`):

| Variable | Purpose |
|----------|---------|
| `LOGTO_DB_DATABASE` / `LOGTO_PORT` / `LOGTO_ADMIN_PORT` / `LOGTO_ENDPOINT` / `LOGTO_ADMIN_ENDPOINT` | Logto compose service wiring |
| `JWT_JWKS_FILE` | Local JWKS exported from Logto; presence turns authentication **on** |
| `JWT_AUDIENCE` | API resource URI registered in the Logto Console |
| `JWT_ISSUER` | `$LOGTO_ENDPOINT/oidc`; pins the accepted issuer |
| `JWT_ALGORITHM` | `ES384` (default; Logto's signing algorithm) |
| `JWT_VERIFICATION_KEY` | Symmetric HS256 key for local development **instead of** Logto (see §5) |

With neither `JWT_JWKS_FILE` nor `JWT_VERIFICATION_KEY` set the Runtime
boots open (no authentication) — that is the pre-v0.6.0 development mode,
not a deployment configuration. Setting `JWT_AUDIENCE`/`JWT_ISSUER`
without key material fails fast at startup.

Web Client: `VITE_LOGTO_ENDPOINT`, `VITE_LOGTO_APP_ID`,
`VITE_LOGTO_API_RESOURCE` (see the client repo's `.env.example`).

## 4. Logto Operations Runbook

### First-time deployment

1. `docker compose up -d` (the `logto` service shares the `spectres-db`
   PostgreSQL container and stores its data in `LOGTO_DB_DATABASE`).
2. First boot against an empty database requires the seed, run once:
   `docker compose run --rm --entrypoint npm logto -w /etc/logto run db seed`
   (then `... run alteration deploy latest` if the image tag moved since).
3. If startup fails on a missing-RLS check for `_logto_configs`:
   `ALTER TABLE _logto_configs ENABLE ROW LEVEL SECURITY;` (ENABLE, not
   FORCE) on the Logto database.
4. Console at `http://localhost:3002`: register the admin account (first
   user becomes Console admin), create the **API resource** (identifier =
   `JWT_AUDIENCE`), create the **SPA application** (redirect URIs of the
   Web Client), create end users under User management.
5. Export the JWKS for the Runtime:
   `curl -sf $LOGTO_ENDPOINT/oidc/jwks > docker/logto/jwks.json`
   (gitignored; never committed).

### Key rotation

Logto never rotates signing keys automatically, so the exported JWKS file
stays valid indefinitely. After a **manual** rotation
(`logto db config rotate oidc.privateKeys`): re-export the JWKS (step 5)
and restart the Runtime. Until then, tokens signed with the new key fail
verification.

### Upgrades

Logto upgrades are two-step by design: bump the image tag, then run
`docker compose run --rm --entrypoint npm logto -w /etc/logto run alteration deploy latest`
**before** starting the new version — the app refuses to boot on a pending
alteration.

### Smoke test (M2M token)

Create a Machine-to-Machine app in the Console with a role holding a
permission of the Runtime API resource, then:

```bash
curl -sf -X POST $LOGTO_ENDPOINT/oidc/token \
  -d grant_type=client_credentials -d client_id=<id> -d client_secret=<secret> \
  -d resource=https://spectres.runtime/api -d scope=<permission>
curl -H "Authorization: Bearer <access_token>" http://localhost:7777/agents
```

## 5. Local Development Without Logto (Dev Tokens)

For curl-driven development and tests, skip Logto entirely: set
`JWT_VERIFICATION_KEY` to a symmetric secret (and
`JWT_ALGORITHM=HS256`/`JWT_AUDIENCE` to match), then mint tokens with
Agno's helper (see `tests/test_auth.py` for the working pattern):

```python
from agno.os.auth import create_dev_token
token = create_dev_token(
    "dev-user",
    secret=<JWT_VERIFICATION_KEY>, audience=<JWT_AUDIENCE>,
    scopes=["agent_os:admin"],  # optional: cross-user data break-glass
)
```

This exercises the exact same middleware path as a Logto token. The
scheduled-tasks channel (AgentOS internal service token) is independent of
JWT configuration and keeps working in both modes.
