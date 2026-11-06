# Authentication and Authorization

> Current Logto/JWT integration and AgentOS scope enforcement. Decision history:
> ADR 0009 and ADR 0010. Last updated: 2026-11-06.

## 1. Request Path

```text
Web Client ──auth code + PKCE──> Logto (:3001/:3002)
Web Client <──JWT access token── Logto
Web Client ──Bearer JWT────────> Runtime / AgentOS (:7777)
```

AgentOS verifies the token signature, issuer, and audience locally, then enforces
Agno-native scopes. Logto uses its own database in the shared PostgreSQL
container; Runtime exports Logto's JWKS to a local file.

- Routes require a verified Bearer JWT except `/health` and documentation
  endpoints. Missing/invalid tokens return 401; disabled users or insufficient
  permissions return 401/403 depending on the middleware path.
- JWT `sub` is the Runtime `user_id` and directory `/users.id`.
- AgentOS just-in-time provisions `ai.agno_authz_users`.
  `UserProfileSyncMiddleware` refreshes the display name from later tokens.
  Setting directory `disabled` denies access even while a token remains valid.
- Logto owns `user`/`admin` roles and assignments. Runtime has no separate role
  store or custom `/authz` API.
- [Per-user isolation](data-isolation.md) is separate from authentication and
  scope authorization. `agent_os:admin` is the cross-user break-glass scope.

## 2. Token Contract

| Claim | Runtime use |
|-------|-------------|
| `iss` | Must match `JWT_ISSUER`, normally `$LOGTO_ENDPOINT/oidc` |
| `aud` | Must match `JWT_AUDIENCE`, normally `https://spectres.runtime/api` |
| `sub` | Authenticated user or machine identity |
| `name` | User-directory display name, refreshed on authenticated requests |
| `scopes` | String array of Agno-native permissions |
| signature | Verified using `JWT_JWKS_FILE` or the local symmetric key |

The Web Client must request the configured API resource; otherwise Logto may
return an opaque token that Runtime cannot use. Agno reads the custom `scopes`
array, not the standard space-delimited OAuth `scope` string.

The current ordinary `user` role includes config/registry/agent reads,
`agents:*:run`, `workflows:read`, global `workflows:run`, session/memory/
schedule/approval read-write-delete scopes, and metrics/trace reads. Global
Workflow permission lets ordinary users run and schedule every registered
Workflow, including `etf_grid_data_sync`; it does not permit arbitrary extension
HTTP schedule targets. The `admin` role carries `agent_os:admin`.

ETF Grid custom routes explicitly self-scope normal portfolio operations for
both users and administrators. Instrument administration and composite
`/refresh` require `agent_os:admin` or the verified internal caller; `/sync` is
available to any authenticated user or internal caller.

## 3. Configuration

| Variable | Purpose |
|----------|---------|
| `LOGTO_DB_DATABASE`, `LOGTO_PORT`, `LOGTO_ADMIN_PORT` | Compose service wiring |
| `LOGTO_ENDPOINT`, `LOGTO_ADMIN_ENDPOINT` | Public Logto and Console endpoints |
| `JWT_JWKS_FILE` | Exported Logto JWKS; enables JWT authentication |
| `JWT_AUDIENCE`, `JWT_ISSUER` | Accepted token audience and issuer |
| `JWT_ALGORITHM` | `ES384` by default for Logto |
| `JWT_VERIFICATION_KEY` | Symmetric local-development key instead of JWKS |

Without either verification key, Runtime starts in open local-development mode.
This is not a deployment security configuration. Configuring an audience or
issuer without key material fails settings validation.

## 4. Logto Setup and Operations

### Initial setup

1. Start services with both environment layers:

   ```bash
   docker compose --env-file .env --env-file .env.local up -d
   ```

2. Seed an empty Logto database once:

   ```bash
   docker compose --env-file .env --env-file .env.local run --rm --entrypoint npm logto -w /etc/logto run db seed
   ```

3. In Console (`LOGTO_ADMIN_ENDPOINT`), create the API resource using
   `JWT_AUDIENCE`, create the SPA application and redirect URIs, and create users.
4. Export the JWKS to the configured gitignored path:

   ```bash
   curl -sf "$LOGTO_ENDPOINT/oidc/jwks" > docker/logto/jwks.json
   ```

If Logto reports a missing RLS check for `_logto_configs`, enable RLS on that
table in the Logto database. Do not use `FORCE ROW LEVEL SECURITY`.

### Roles and custom claims

Create the Agno scopes as API-resource permissions. Assign ordinary scopes to a
default global `user` role and only `agent_os:admin` to `admin`. Add a trusted
Logto access-token custom-claims script equivalent to:

```javascript
const getCustomJwtClaims = async ({ context }) => {
  const scopes = (context.user?.roles ?? [])
    .flatMap((role) => role.scopes ?? [])
    .filter((scope) => scope.resource?.indicator === "https://spectres.runtime/api")
    .map((scope) => scope.name);
  return { scopes: [...new Set(scopes)], name: context.user?.name };
};
```

The resource filter must match `JWT_AUDIENCE` when it differs from the example.
Role, permission, and profile changes require a refreshed/new token. Verify that
ordinary users can access `/agents` but not `/users`, while admins can access
both. Never log real tokens.

### Rotation and upgrades

After manually rotating Logto OIDC signing keys, re-export the JWKS and restart
Runtime. For a Logto image upgrade, apply pending alterations before starting the
new version:

```bash
docker compose --env-file .env --env-file .env.local run --rm --entrypoint npm logto -w /etc/logto run alteration deploy latest
```

## 5. Local Development Tokens

To exercise the same middleware without Logto, set `JWT_VERIFICATION_KEY`, use
`JWT_ALGORITHM=HS256`, and configure a matching audience. Tests use Agno's helper:

```python
from agno.os.auth import create_dev_token

token = create_dev_token(
    "dev-user",
    secret=<JWT_VERIFICATION_KEY>,
    audience=<JWT_AUDIENCE>,
    scopes=["agent_os:admin"],  # Optional break-glass access
)
```

Use only a local development key. The scheduler's internal service-token channel
is independent of Logto and continues to work in JWT mode.
