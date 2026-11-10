# ADR 0012: Independent Edge Services and Built-in Extension Enablement

- **Status**: Accepted; amended for Mi Health by ADR 0013
- **Date**: 2026-11-07
- **Deciders**: Project owner + architecture discussion

> ADR 0013 reclassifies Mi Health as a built-in Runtime and Web Client Extension
> using the Runtime API token. This ADR remains in force for built-in Extension
> enablement and future services that require independent Edge deployment.

## Context

Spectres needs two different kinds of extensibility:

- **Extensions** are trusted, first-party product capabilities. Their Runtime
  and Web Client code is built and released with the respective projects, but
  administrators must be able to enable or disable each capability without a
  code deployment.
- **Edges** are independently deployed services that connect external clouds,
  software intermediaries, or physical devices. Their data schemas, background
  synchronization, and UI releases must be able to evolve independently of
  Runtime and the Web Client.

The first Edge will be Xiaomi Health. It will authenticate a Spectres user to a
Xiaomi account, synchronize health data from Xiaomi's cloud, persist that data,
and expose configuration, status, and query operations. Runtime may expose
specific Edge operations as AI tools, but Runtime should not manage the Edge's
internal synchronization lifecycle or duplicate its health database.

Current Runtime Extensions are discovered in-tree at startup and are enabled by
presence. Current Web Client extensions are eagerly discovered at build time
through `import.meta.glob`; neither side has administrator-controlled enablement.
The Web Client is a static React/Vite SPA that uses `@logto/react` and Bearer JWTs.
Runtime, Web Client, Logto, and future Edges may run on different hosts and IP
addresses.

Early design exploration considered a generic Edge control plane, Runtime-owned
Edge data ingestion, iframe-embedded Edge UIs, and BFF-managed browser sessions.
Those approaches introduced more infrastructure and browser-session complexity
than the current product requires. Independent UI releases still need a standard
runtime module-loading mechanism rather than a custom plugin loader.

## Decision

### 1. Keep Extensions and Edges as separate architectural mechanisms

Extensions and Edges do not share a loading, release, or enablement model.

| Concern | Extension | Edge |
|---------|-----------|------|
| Code ownership | Runtime and Web Client repositories | Independent Edge/UI project |
| Release | Released with Runtime and Web Client | Independently released |
| Loading | Static startup/build-time loading | Runtime-loaded Web Client remote |
| Administration | Global administrator enable/disable | Independent deployment and availability |
| Typical capability | ETF Grid, Runtime AI integration | Xiaomi Health service and UI |

A Runtime Extension may wrap operations supplied by an Edge. Disabling that
Extension disables only the Runtime integration, such as AI tools and event
handling; it does not stop the Edge's synchronization or disable its UI.

### 2. Treat each Edge as an independent vertical service

An Edge owns its complete backend capability:

- External-service or device authentication and account binding.
- Credential storage and refresh.
- Device and synchronization state.
- Scheduled and manual synchronization.
- Domain data schemas, tables, migrations, and persistence.
- User-facing configuration, status, and query APIs.
- Optional internal APIs intended for a corresponding Runtime Extension.
- Optional event notifications to Runtime.

Xiaomi Health Edge directly writes its own health data to PostgreSQL and owns
the health data schema. Runtime does not create, import, or mutate Edge tables
and does not maintain a second canonical copy of Edge health data. Runtime and
Edge may share a PostgreSQL deployment, but table ownership and access remain
separate.

No generic Connector abstraction, Edge registry, ingestion protocol, Edge
control plane, or custom scheduler is introduced. Runtime-to-Edge calls are
specific operations implemented by a corresponding Runtime Extension. Edge-to-
Runtime calls are optional notifications, not the data-synchronization path.
Events must be authenticated and idempotent; Runtime correctness must not depend
on their delivery.

Every private Edge read and write derives `user_id` from the verified caller or
from a stored binding whose ownership has already been established. Browser or
LLM-supplied ownership fields are never authoritative.

### 3. Keep the Web Client as a pure SPA with Logto-issued API tokens

The browser does not require a Runtime BFF, an Edge BFF, shared session cookies,
or iframe authentication. Logto remains the sole identity authority.

The Web Client uses its existing OIDC authorization-code flow with PKCE through
`@logto/react`. Runtime and each Edge define separate Logto API resources. The
client obtains the access token for the resource it intends to call:

```text
Runtime token: sub = user-123, aud = Runtime API resource
Edge token:    sub = user-123, aud = Edge API resource
```

Both tokens represent the same Logto user through `sub`, which is the common
Spectres `user_id`. Token storage, renewal, and re-authentication remain owned by
the Logto SDK. A second API token does not require a second interactive login.

Runtime and each Edge independently verify the token signature, issuer,
audience, expiry, and required permissions. An Edge must not accept a Runtime
access token. CORS is required for cross-origin module and API requests but is
not treated as an authentication boundary.

The existing Runtime Bearer authentication, Agno scopes, UserDirectory, and
user-isolation behavior remain unchanged. Runtime and Edge do not call each
other to authenticate browser requests.

### 4. Load Edge UI remotes with Module Federation

Use Module Federation with `@module-federation/vite` for independently released
Edge UI pages. Do not use iframes for first-party Edge UIs and do not build a
custom remote-module loader.

The Web Client is the Module Federation host. Each Edge UI is an independently
built Vite remote that exposes a stable page module. The Edge deployment serves
its generated `mf-manifest.json` and static assets.

The Web Client maintains a small, administrator- or deployment-managed Edge
catalog containing only integration metadata such as:

- Stable Edge/plugin id and remote name.
- Remote manifest URL.
- Edge API base URL.
- Permitted Logto API resource.
- Navigation presentation metadata.

At startup, the host registers catalog entries through Module Federation's
runtime API. Navigation can be registered from the catalog without downloading
the full page. When a user opens an Edge page, the host uses `loadRemote()` to
load its stable exposed page lazily. Loading and rendering failures are contained
within that page and do not prevent chat, administration, built-in Extensions,
or other Edge pages from working.

The host passes a narrow page contract containing the Edge API base URL, a token
getter bound to the catalog-approved API resource, locale, theme, and cancellation
support. It does not pass Runtime tokens or expose unrestricted token acquisition.
Remote page props and exposed module names form a stable compatibility contract;
Module Federation's own manifest does not replace this Spectres-specific metadata.

Share only compatible React runtime dependencies, including React and React DOM,
as singletons. Edge-specific libraries remain private to each remote. Initial
Edge remotes provide navigation pages only; direct CopilotKit tool-card or other
framework-internal contributions are deferred to avoid coupling remote releases
to host framework internals.

Edge UI assets use content-hashed, long-lived cache entries, while the remote
manifest is revalidated on application startup or page refresh. An Edge release
updates its manifest and assets without rebuilding the Web Client. Old assets
are retained for rollback, and production remotes are not hot-replaced during an
active user session.

Module Federation provides code loading, not a security sandbox. Only reviewed,
first-party Edge remotes from approved origins may be loaded. A future untrusted
plugin model would require a separate isolation design.

### 5. Keep Extension code static and add persistent runtime enablement

Retain the existing in-tree Runtime discovery, idempotent `register()` contract,
fail-loud startup, and eager Web Client build-time discovery. Extension code is
always present and type-checked or started with its owning project.

Separate discovery and registration from activation:

```text
static discovery -> registration -> runtime activation check
```

Each Runtime Extension manifest declares a stable snake_case `id`, a
human-readable `name`, and a `description`. Runtime persists one global state
row per known Extension, keyed by `id`; display metadata comes from the
discovered code rather than the state table. A newly introduced Extension
defaults to enabled so existing behavior is preserved. Startup inserts missing state rows but never overwrites
an administrator's stored choice. State rows for removed code need not be
deleted automatically.

Only `agent_os:admin` may change Extension state. Authenticated clients may read
the current catalog to determine which built-in Extension UI surfaces to show.
All state changes emit an audit log without secrets.

Disabled Extensions remain registered with the framework so that enablement does
not require a restart or dynamic reconstruction of AgentOS components. Runtime
is the authoritative enforcement boundary:

- Extension routers reject new calls with a structured `extension_disabled`
  error.
- Toolkit entry points return the standard structured tool error and perform no
  business operation.
- Workflows stop before their first business side effect.
- Scheduled triggers encounter the same Workflow or API guard and therefore
  produce no business side effect.

Disabling an Extension does not delete its tables or data, cancel an already
running operation, rewrite user Schedules, or overwrite their independent
enabled settings. Re-enabling preserves existing configuration and data.

Runtime retains the association between an Extension id and its contribution
after discovery so that router, Toolkit, Workflow, audit, and catalog guards do
not rely on a second package scan. Extension identity is distinct from Web
Client view and navigation ids; no implicit route-name conversion is treated as
an ownership or state key.

The Web Client continues to bundle all built-in Extensions. It filters Extension
navigation, views, and tool-card registration from the Runtime catalog. This is
presentation behavior only and is never a substitute for Runtime enforcement.
The core Extension management UI remains available when any individual Extension
is disabled. Other open clients may update on refresh or their next catalog
refresh; Runtime enforcement is immediate.

## Alternatives Considered

- **One generic plugin model for Extensions and Edges**: rejected because their
  trust, release, deployment, and availability requirements are fundamentally
  different.
- **Runtime-owned Edge ingestion and canonical data tables**: rejected for the
  current scope because it duplicates Edge persistence and adds a generic
  protocol that the independent services do not need.
- **Iframe-embedded Edge UIs with independent BFF sessions**: rejected because
  iframe SSO, third-party cookies, logout coordination, and cross-site deployment
  add unnecessary complexity. First-party Edge UIs use Module Federation instead.
- **Runtime as the browser BFF**: viable but unnecessary for the selected pure-SPA
  model. Resource-specific Bearer tokens already provide consistent identity
  without introducing server-side browser sessions.
- **Sharing Runtime tokens or session cookies with Edges**: rejected because it
  weakens audience isolation and couples service session lifecycles.
- **Building Edge UI source into the Web Client**: rejected for Edges because it
  requires a Web Client release for every Edge UI update. It remains the model
  for built-in Extensions.
- **A custom manifest plus native ESM mount/unmount loader**: workable, but would
  reimplement remote loading, metadata, caching, and dependency-sharing concerns
  already covered by Module Federation.
- **single-spa or Piral**: both are viable microfrontend frameworks. single-spa
  adds application lifecycle, routing, and module-map orchestration that the
  page-level Edge integration does not need; Piral introduces a broader React
  plugin platform and feed model. Module Federation fits the existing Vite/React
  host with less architectural replacement.
- **Skipping registration of disabled Extensions**: rejected because runtime
  toggling would then require component reconstruction or a restart. Persistent
  activation guards are simpler and preserve stored configuration.
- **Client-only Extension disabling**: rejected because hidden navigation does
  not prevent API, tool, Workflow, or scheduled execution.

## Consequences

- Extension updates continue to require normal Runtime and Web Client releases;
  Edge backend and UI releases can proceed independently.
- Administrators gain global Extension enablement without an uninstall or data
  deletion semantic. Existing Extensions default to enabled during migration.
- Disabled Extension tools and Workflows may remain visible in framework
  catalogs, but execution fails closed. Schedules may still fire and record a
  disabled result rather than business execution; preserving their independent
  configuration is more important than suppressing every trigger in the first
  implementation.
- Each Edge requires Logto API-resource configuration, JWT verification, and
  CORS configuration for remote assets and API calls. Different hosts and IP
  addresses do not require shared cookies or a BFF.
- Web Client startup depends on Edge manifests only for those optional remote
  pages. An unavailable Edge degrades its own navigation/page and does not block
  the core application.
- React major-version compatibility becomes a shared host/remote contract. Other
  Edge UI dependencies can evolve independently.
- First-party remote code executes with the Web Client's page privileges. Remote
  origin allowlisting, HTTPS, build review, and asset integrity are operational
  requirements; Module Federation must not be described as a security boundary.
- Runtime and Edge remain independently available for their respective roles.
  AI integration can fail or be disabled without stopping Edge synchronization,
  and an Edge outage does not disable unrelated Runtime capabilities.
- The accepted design does not imply that Edge services, Module Federation
  remotes, or administrator Extension enablement are already implemented.

## References

- Module Federation Vite integration: https://module-federation.io/integrations/build-tool/vite
- Module Federation Runtime API: https://module-federation.io/guide/runtime/runtime-api
- Module Federation manifest and snapshot: https://module-federation.io/guide/basic/manifest-snapshot
- Module Federation shared dependencies: https://module-federation.io/configure/shared.html
- ADR 0003: Automation Trigger Layers and Session Isolation
- ADR 0008: Cloud Gateway as the Public Entry Point
- ADR 0009: Identity Provider — Logto OSS Self-Hosted
- ADR 0010: Authorization — Logto RBAC with Agno JWT Scopes
- ADR 0011: Extension Workflows for Scheduled Tasks
