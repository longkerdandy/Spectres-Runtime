# ADR 0010: Authorization — Logto RBAC with Agno JWT Scopes

- **Status**: Accepted
- **Date**: 2026-10-29
- **Deciders**: Project owner + architecture discussion

## Context

ADR 0009 established Logto as the identity provider and Runtime as the JWT
verifier. v0.6.0 intentionally gave every authenticated user identical route
permissions through a custom `AnyAuthenticatedProvider`. v0.6.1 added
row-level user isolation and Agno's existing `agent_os:admin` break-glass.

The next milestone needs a real administrator without duplicating user and
role administration across two control planes. The administrator is a pure
management experience in the Web Client, while Runtime retains Agno's full
admin API and cross-user capabilities.

Agno's self-hosted guidance recommends defining roles in the identity
provider or backend and including native Agno scopes in the JWT. Logto
already provides global/default roles, API-resource permissions, and custom
JWT claims.

## Decision

**Logto owns users, roles, and role assignments; Runtime enforces the
resulting JWT scopes through Agno's built-in scope provider.**

- Define a default global `user` role with only current product scopes and
  an `admin` role containing `agent_os:admin`.
- Reuse the existing Runtime API resource and its Agno-native permissions.
- Use Logto `getCustomJwtClaims` to emit those granted permissions as
  `scopes: string[]`. The standard space-delimited OAuth `scope` string is
  not a compatible substitute because Agno does not split it.
- Remove `AnyAuthenticatedProvider`; verify-only `Authorization` uses Agno's
  default `ScopeAuthorizationProvider`. No Runtime role store, `/authz`,
  `ADMIN_USER_ID`, `seed()`, `roles_claim`, or custom isolation middleware.
- Keep UserDirectory and its disabled-user kill-switch. `/users` is
  admin-only; role management remains in Logto Console.
- Keep `user_isolation=True`. `agent_os:admin` retains Agno's full API and
  cross-user break-glass even though the Web Client presents a
  management-only console (Web Client v0.3.1).
- Extensions remain outside this authorization milestone.

## Alternatives Considered

- **Agno managed roles in Runtime**: provides `/authz` and immediate
  request-time assignment changes, but duplicates role administration outside
  Logto and needs a custom integration for role-derived isolation bypass.
  Rejected for this family-scale deployment.
- **Logto roles through `roles_claim`**: keeps Logto assignments but still
  requires Runtime role definitions and does not directly provide the
  token-scope admin behavior used by isolation. JWT scopes are the simpler
  official path.
- **Keep all authenticated users equal**: rejected because it provides no
  administrative boundary.
- **Restrict admin backend access to management endpoints only**: rejected.
  The management-only experience is a Client concern; Runtime keeps Agno's
  standard superuser break-glass.

## Consequences

- Users and roles have one administrative home: Logto Console.
- Role and permission changes affect newly issued access tokens, so they take
  effect after refresh or re-login rather than on the next request. Runtime's
  disabled-user flag remains the immediate revocation mechanism.
- Custom JWT scripts are privileged Logto host code and must be editable only
  by trusted administrators. Token contents must be verified for both roles;
  tokens themselves are never logged or committed.
- Runtime authorization becomes smaller: no custom role system or middleware
  is required beyond removing the flat provider.
- Ordinary users lose access to admin-only framework operations they could
  previously call, while daily agent/session/memory/schedule functionality
  remains covered by the `user` scope set.
- The standard Logto `scope` string and Agno `scopes` array are different
  contracts; the custom-claims step is a required compatibility boundary and
  must be regression-tested with real Logto tokens.

## References

- Agno Roles: https://docs.agno.com/agent-os/security/authorization/roles
- Agno Self-Hosted Authorization: https://docs.agno.com/agent-os/security/authorization/self-hosted
- Agno Tokens and Scopes: https://docs.agno.com/agent-os/security/authorization/tokens
- Logto RBAC: https://docs.logto.io/authorization/role-based-access-control
- Logto Custom Access Token: https://docs.logto.io/developers/custom-token-claims
- ADR 0009: Identity Provider — Logto OSS Self-Hosted
