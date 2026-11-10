# ADR 0013: Mi Health as Built-in Extensions

- **Status**: Accepted
- **Date**: 2026-11-10
- **Deciders**: Project owner + architecture discussion
- **Amends**: ADR 0012 for the Mi Health classification and authentication boundary

## Context

ADR 0012 classified Xiaomi Mi Health as the first independently deployed Edge
service. That decision assumed that independent backend and UI releases,
deployment, availability, and API-token isolation were useful requirements for
this capability. It therefore placed the backend outside Runtime, loaded the UI
as a future Module Federation remote, and required a separate Logto API
resource and access token.

The immediate requirement is narrower: place Mi Health inside Runtime's existing
trusted, first-party deployment boundary. Independent releases, independent
scaling, and deployment on a separate device are possible future requirements,
not current acceptance criteria.

Runtime and the Web Client already have vertical-slice Extension mechanisms.
Runtime statically discovers in-tree backend Extensions and provides routes,
Toolkit, Workflow, Schedule, persistence, authentication, ownership, and global
activation contracts. The Web Client discovers built-in Extension contributions
at build time. These mechanisms support Mi Health without a new backend plugin
platform or an independent service boundary.

The existing Spectres-Edge-Mi-Health repository contains protocol research,
synthetic fixtures, and a walking skeleton. This decision does not convert that
skeleton into production behavior or invalidate the research evidence.

## Decision

### 1. Classify Mi Health as a built-in vertical Extension

Mi Health is a trusted, first-party Runtime and Web Client Extension in the
current product topology, not an independent Edge service.

Its code belongs in:

```text
Spectres-Runtime/src/spectres/extensions/mi_health/
Spectres-Web-Client/src/extensions/mi-health/
```

The shared Extension id is `mi_health`. Backend routes follow the existing
`/api/v1/extensions/mi-health/` convention. The backend Extension owns the Mi
Health domain services, Xiaomi account binding, credential lifecycle,
synchronization state, health-data persistence, and user-facing API adapters.
It may contribute REST routes, Toolkits, Workflows, and declarative Schedules
through the existing `register()` contract.

Runtime Core must not import Mi Health code. The Web Client discovers its
navigation, views, locales, and any approved tool-card contributions through
the existing built-in Extension registry. Mi Health backend and UI releases are
included with their respective Runtime and Web Client releases.

Do not introduce out-of-tree backend installation, hot loading, a generic
plugin control plane, or a second scheduler for Mi Health. Module Federation
remains reserved for future independently released Edge UIs; the built-in Mi
Health UI uses build-time loading.

### 2. Use the Runtime API token without separate Mi Health scopes

The Web Client uses its existing Logto authorization-code flow with PKCE and
obtains the Runtime API access token. Mi Health routes are Runtime routes and
use the same issuer, audience, signature, expiry, and identity verification.
There is no separate Mi Health audience or browser token in the built-in
Extension topology.

All authenticated Runtime users may use Mi Health while the Extension is
globally enabled. Do not define a dedicated Mi Health permission or role for
the initial implementation. This matches the existing ETF Grid authorization
model and avoids adding a per-user or role-based feature entitlement before
the product requires one. Runtime authentication and Extension activation
apply consistently to Mi Health REST routes, Toolkits, and Workflows. A future
requirement for role-based access or distinct read, write, and administration
permissions requires a new or amended ADR and consistent enforcement across
all contributed execution surfaces.

Every private read and write derives `user_id` from verified
`request.state.user_id` or `RunContext.user_id`. Browser parameters, request
bodies, and LLM arguments are never authoritative ownership inputs. Mi Health
uses its own Extension-prefixed tables and must not access Agno-managed or
other Extensions' tables. Per-user isolation prevents cross-user access but
does not replace credential protection or other security controls. Xiaomi
credentials, tokens, sensitive login URLs, and health data must never be
logged or committed.

### 3. Reuse Runtime activation and scheduling semantics

Mi Health uses the existing global Extension enablement and execution guards.
Disabling the Extension prevents new REST, Toolkit, and Workflow business
operations according to the shared Runtime contract; it does not delete data or
rewrite user-owned Schedules.

Scheduled synchronization uses extension Workflows and Agno-native Schedules.
Operations must be idempotent and preserve the bounded retry, renewal, and
atomic session-rotation constraints established by the Xiaomi authentication
research. Runtime hosts the execution lifecycle, but Mi Health remains
responsible for its own domain state and synchronization correctness.

### 4. Defer parallel development environment research

Parallel agent development using Git worktrees, separate clones, dedicated
dependency environments, or database and port isolation is deferred until the
product functionality is more mature and there is a concrete recurring need for
it. Do not establish a parallel development environment as part of the Mi Health
transition. Continue using the existing development workflow.

A future development-workflow decision must evaluate the operational complexity,
shared external resources, and integration requirements independently of the Mi
Health runtime topology.

### 5. Defer an independent Edge split until it is required

Keep Mi Health domain services cohesive and FastAPI, Agno, and UI adapters thin
so a future extraction is possible. Do not maintain both in-process and
standalone deployment modes now.

A future requirement to run Mi Health on a separate device, release or scale it
independently, or place it behind a distinct security boundary requires a new
or amended ADR. That decision may reintroduce an independent FastAPI service,
a dedicated Logto API resource and token, and a Module Federation UI remote.
Repository separation or token separation is not required in anticipation of
that scenario.

ADR 0012 remains in force for built-in Extension enablement and for future
services that genuinely require independent Edge deployment. Its classification
of Mi Health as the first independent Edge and its application of a separate
Edge token to Mi Health are amended by this ADR.

## Alternatives Considered

- **Keep Mi Health as an independent Edge service**: provides deployment and
  audience isolation, but adds a second API resource, token lifecycle, service
  deployment, CORS configuration, and cross-service integration without a
  current requirement for those boundaries. Deferred.
- **Build backend and frontend artifacts from a separate Mi Health repository**:
  supports independent code ownership and frontend releases, but requires a
  new out-of-tree Runtime loading, dependency, migration, and compatibility
  contract. That cost is not justified for the current trusted first-party
  topology. Rejected.
- **Require dedicated Mi Health scopes from the initial implementation**:
  would support role-based feature entitlement, but no current requirement
  limits Mi Health to a subset of authenticated Runtime users. Deferred; a
  future permission model must cover REST, Toolkit, and Workflow entry points
  consistently.
- **Add dynamic backend plugins to imitate the future Edge UI loader**: creates
  installation, compatibility, security, and lifecycle complexity that static
  first-party Extensions do not need. Rejected.

## Consequences

- No parallel development environment is established for Mi Health. Worktrees,
  separate clones, and related resource-isolation strategies require later
  research before adoption.
- Mi Health uses the existing Runtime browser token and authorization model.
  Every authenticated Runtime user may use the globally enabled Extension; no
  dedicated Mi Health permission or role is required. A second login was never
  required, and a second API token is also unnecessary.
- Per-user ownership isolation remains the control against cross-user data
  access. It does not eliminate credential, logging, or in-process security
  risks.
- Mi Health backend and frontend changes require Runtime and Web Client
  releases respectively. Independent deployment, scaling, restart, and UI
  release are not provided.
- Mi Health shares Runtime's process, dependency, availability, and security
  boundary. A Runtime compromise or faulty in-process module can affect Mi
  Health and vice versa; this is accepted for the current trusted first-party
  deployment.
- The independent Edge skeleton, dedicated Logto Edge resource, project
  guidance, and living architecture documents were migration inputs, not
  evidence that the built-in Extension was implemented. Reusable protocol
  research is preserved under `docs/research/mi-health/`, and the old independent
  service topology is superseded.
- This ADR records an accepted target architecture. It does not implement the
  Mi Health Extension, migrate the existing skeleton, change Logto, or add a
  Module Federation runtime.

## References

- ADR 0010: Authorization — Logto RBAC with Agno JWT Scopes
- ADR 0012: Independent Edge Services and Built-in Extension Enablement
- Runtime Extensions architecture: `docs/architecture/runtime-extensions.md`
- Web Client frontend architecture: `../Spectres-Web-Client/docs/frontend-architecture.md`
- Mi Health authentication research: `docs/research/mi-health/mi-fitness-authentication-contract.md`
