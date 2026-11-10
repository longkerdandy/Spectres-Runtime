# Authentication and Authorization

> Current Runtime authentication/authorization contracts and accepted Extension
> and Edge identity boundaries for coding agents. Last updated: 2026-11-10.

## 1. Current Request Path

```text
Web Client ──authorization code + PKCE──▶ Logto
Web Client ◀──Runtime API access token──── Logto
Web Client ──Bearer JWT─────────────────▶ Runtime / AgentOS
```

AgentOS verifies the token locally and enforces Agno-native scopes. Runtime does
not call Logto to authenticate each request and does not query Logto's internal
database.

Except for documented health and documentation endpoints, routes require a
verified Bearer JWT. Missing/invalid tokens return 401; disabled users or
insufficient permissions produce 401/403 according to the middleware path.

## 2. Verified Token Contract

| Claim/material | Runtime rule |
|----------------|--------------|
| `iss` | Must match `JWT_ISSUER` |
| `aud` | Must match the Runtime API resource in `JWT_AUDIENCE` |
| `sub` | Verified Runtime `user_id` and user-directory `/users.id` |
| `name` | Optional display name synchronized to the user directory |
| `scopes` | String array of Agno-native permissions |
| `exp`, signature | Verified using `JWT_JWKS_FILE` or the configured local-development key |

The Web Client must request the Runtime API resource; otherwise Logto may issue
an opaque token Runtime cannot use. Agno reads the custom `scopes` array, not the
standard space-delimited OAuth `scope` string.

AgentOS just-in-time provisions `ai.agno_authz_users`.
`UserProfileSyncMiddleware` refreshes display names from later tokens. A disabled
directory user is denied even while the JWT remains valid.

## 3. Authorization Boundaries

- Logto owns users, `user`/`admin` roles, and role assignments. Runtime has no
  separate role store or custom `/authz` API.
- `agent_os:admin` is the framework administration and cross-user break-glass
  scope. It does not automatically make Extension business routes cross-user.
- The ordinary role currently has global `workflows:run`, so it can run and
  schedule every registered Workflow, including shared ETF Grid data sync. It
  cannot select arbitrary Extension HTTP Schedule targets.
- ETF Grid portfolio routes self-scope both ordinary users and administrators.
  Shared `/sync` accepts an authenticated user or the verified internal caller;
  current-user signal computation never accepts an ownership override.
- Core Extension catalog reads require an authenticated identity; activation
  changes require `agent_os:admin`. Disabled Extension guards apply equally to
  ordinary, administrator, and verified internal callers.
- Scope authorization and data ownership are separate. Every custom private
  operation must still enforce [Data Isolation](system-architecture.md).

## 4. Configuration and Failure Modes

| Variable | Purpose |
|----------|---------|
| `JWT_JWKS_FILE` | Exported Logto public keys; enables JWT authentication |
| `JWT_AUDIENCE`, `JWT_ISSUER` | Required accepted Runtime token audience and issuer |
| `JWT_ALGORITHM` | Accepted signature algorithm, normally Logto `ES384` |
| `JWT_VERIFICATION_KEY` | Symmetric local-development key instead of JWKS |

Without JWKS or a verification key, Runtime starts in open local-development
mode. This is not a deployment security configuration. Configuring an audience or
issuer without verification material fails settings validation.

Tests can use Agno's `create_dev_token` with a local-only symmetric key. Never
commit or log real tokens, signing keys, or verification secrets.

## 5. Scheduler Identity

The scheduler's internal service-token channel is independent of Logto browser
tokens. For an owned Schedule, only the verified internal scheduler identity may
forward the stored owner to the Workflow/HTTP target. Client payloads, query
parameters, and forwarded headers must not establish ownership.

Preserve this separation when changing scheduler authentication, Workflow
ownership, or internal Extension routes.

## 6. Target Extension and Edge Identity Boundaries

### 6.1 Built-in Mi Health Extension

ADR 0013 accepts Mi Health as a planned built-in Extension; it is not currently
implemented:

- Mi Health uses the existing Runtime API resource, access token, authentication,
  and global Extension activation. Every authenticated Runtime user may use it
  while enabled.
- No dedicated Mi Health API resource, audience, permission, or role is required.
  A future role-based entitlement requires a separate reviewed decision.
- Every private read and write derives ownership from verified
  `request.state.user_id` or `RunContext.user_id`. Browser input and LLM arguments
  are never authoritative ownership inputs.
- Per-user isolation addresses cross-user access but does not replace credential
  protection, sensitive-log prevention, or other security controls.

### 6.2 Independent Edge Services

ADR 0012 accepts the following design for future services that genuinely require
independent Edge deployment; Edge authentication is not currently implemented:

- Runtime and each Edge define separate Logto API resources and audiences.
- The pure SPA obtains the token for the service it intends to call. A second API
  token does not require a second interactive login or a BFF session.
- The verified `sub` is the common Spectres `user_id` across Runtime and Edges.
- Each service independently verifies signature, issuer, audience, expiry, and
  required permissions. An Edge must reject Runtime-audience tokens.
- Runtime tokens are never forwarded as Edge credentials, and services do not
  call each other to authenticate browser requests.
- CORS permits configured cross-origin browser calls but is not an authentication
  boundary.

## 7. Coding Agent Guardrails

1. Derive identity only from verified request/run context; never from payloads,
   query parameters, forwarded properties, or LLM arguments.
2. Use AgentOS authentication and native scopes rather than adding a parallel
   role store, token format, or authorization dispatcher.
3. Do not treat administrator scope, CORS, catalog visibility, or Extension
   activation as a substitute for owner filtering.
4. Keep public health/documentation exceptions explicit; do not silently disable
   authentication to make a deployment start.
5. Preserve coverage in `tests/test_auth.py`, `tests/test_authorization.py`,
   `tests/test_user_isolation.py`, and the Schedule ownership/API tests when
   changing these boundaries.
