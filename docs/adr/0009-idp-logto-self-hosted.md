# ADR 0009: Identity Provider — Logto OSS Self-Hosted

- **Status**: Accepted
- **Date**: 2026-10-22
- **Deciders**: Project owner + architecture discussion

## Context

Multi-user support (v0.6.x) requires per-user authentication. Agno AgentOS
only **verifies** JWTs — it never issues them and never stores passwords
(`agno/os/authz/user_directory.py`), so an external identity system must
own login, credential storage, and token issuance.

Hard constraints surfaced while planning v0.6.0:

1. **Verification is static-key only.** Agno's `JWTValidator` accepts a
   `verification_keys` list or a **local JWKS file** — there is no JWKS URL
   fetching and no automatic key-rotation following
   (`agno/os/middleware/jwt.py:154-223`). An IdP that rotates signing keys
   automatically forces a file-refresh + Runtime restart every cycle.
2. Users are in mainland China; browser-side redirects to the IdP must be
   reachable without a proxy.
3. Scale is family-grade (<10 users); no self-registration, no roles in
   this phase (ADR 0008: auth is Runtime-side; all users equal for now).
4. The Web Client is a pure static SPA needing Authorization Code + PKCE
   + refresh tokens.
5. Project philosophy: minimize third-party control-plane dependencies
   (the same reasoning that retired Tailscale, ADR 0008).

## Decision

**Adopt Logto OSS (Community) in self-hosted mode as the identity
provider.**

- **Deployment**: a `logto` service (official image `svhd/logto`) added to
  the home host's Docker Compose, backed by the existing PostgreSQL
  instance (own database). One-off `db seed` at first boot; Console used
  for application registration and user management.
- **Client integration**: Web Client uses the official `@logto/react` SDK
  (`LogtoProvider` + hooks; SDK requests `offline_access` and auto-refreshes
  access tokens).
- **Runtime integration**: export Logto's JWKS once to a local file trusted
  via `JWT_JWKS_FILE` (or pass keys via `Authorization(verification_keys=
  ...)`). Logto OSS signing keys **never rotate automatically** (vendor
  statement: "signing keys do not have an expiration time"), so the
  exported file stays valid indefinitely. If a manual rotation is ever
  performed (`logto db config rotate oidc.privateKeys`), the procedure is:
  re-export JWKS → restart Runtime.
- **Token contract**: Logto signs access tokens with ES384 (the OIDC
  signing key generated at first boot); the Runtime validates
  signature + issuer + audience (`aud` = the API resource registered for
  the Runtime). `sub` becomes the AgentOS `user_id` throughout (directory,
  isolation in v0.6.1).
- **Cost scope**: OSS Community features only — username/password login,
  OIDC/PKCE/refresh tokens, TOTP MFA, passkeys, Management API. No
  Self-Hosted Pro features (custom sign-in UI, brand removal, Console
  members). The "Powered by Logto" brand on the sign-in page is accepted.

## Alternatives Considered

- **Casdoor** (self-hosted, Go): strong on weight (single binary, SQLite
  option), free white-labeling, and China-friendliness. Rejected: notably
  higher CVE density in 2025-2026 (including an auth-bypass via arbitrary
  signing certificate, VU#780781, and a CVSS 9.4 authorization bypass),
  self-developed OIDC with open conformance issues (#3602), and no React
  SDK (bare imperative JS SDK only) — the sign-in entry will face the
  public internet, so security track record and protocol rigor weigh most.
- **Pocket ID**: lightest (single container + SQLite, static keys), but
  passkey-only — no password fallback — and no SPA SDK. Rejected for
  family usability.
- **Authentik**: full-featured but heaviest (4 components, 2C/2G minimum),
  and its default self-signed certificate expires after 1 year. Rejected
  as oversized for <10 users.
- **Keycloak**: the de-facto standard, but JVM footprint and configuration
  complexity are unjustifiable at this scale. Rejected.
- **Kanidm / Dex / Ory Hydra+Kratos**: eliminated on hard constraints —
  Kanidm has no refresh tokens; Dex auto-rotates signing keys with no
  off-switch and has no user management; Hydra+Kratos is headless and
  would require building our own login UI.
- **Managed SaaS (Clerk, Auth0)**: excluded by decision — third-party
  control-plane dependency; Auth0 additionally has confirmed
  mainland-China reachability problems.
- **Self-issued JWT (own login endpoint + argon2 user table)**: seriously
  considered — smallest code footprint and zero new services. Rejected in
  favor of Logto because the Runtime would take on credential storage,
  refresh-token rotation, brute-force defense, and account management as
  permanent in-house security surface; Logto's official React SDK also
  removes a full client-milestone of wiring. The migration path back is
  cheap if ever needed: keep `sub` values stable and swap the verification
  key source.

## Consequences

- **A new permanent service**: Logto + its schema in PostgreSQL joins the
  home stack (≈512MB–1GB RAM). It sits on the critical login path: Logto
  down = no new logins (existing unexpired tokens still verify locally,
  since validation is offline against the JWKS file).
- **Upgrade discipline**: Logto upgrades require running the database
  alteration CLI (`npm run alteration deploy latest`) before the new
  version boots; forgetting it blocks startup by design. Added to the ops
  runbook.
- **Open-core drift risk**: Logto has begun moving features into the paid
  Self-Hosted Pro tier (v1.45.0: custom sign-in UI, brand removal).
  Accepted for now — nothing we use is in the paid tier; if drift reaches
  core OIDC features, Casdoor is the standing fallback.
- **Login UX**: sign-in page carries Logto branding (removal is a paid
  feature); SMTP connector must be configured for self-service password
  reset, otherwise password resets are an admin operation in the Console.
- **Client and Runtime stay portable**: the Runtime sees a standard JWT
  (ES384 + iss/aud) and the Web Client a standard OIDC flow; swapping the
  IdP later touches only the SDK setup and the verification key source.
- **Security posture**: login, password storage, refresh-token rotation,
  MFA, and brute-force defenses are owned by a maintained, OpenID-
  certified-stack product rather than by Runtime code.
