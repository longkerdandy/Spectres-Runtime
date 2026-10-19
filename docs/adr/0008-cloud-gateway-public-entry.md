# ADR 0008: Cloud Gateway as the Public Entry Point

- **Status**: Accepted
- **Date**: 2026-10-19
- **Deciders**: Project owner + architecture discussion
- **Supersedes**: parts of [ADR 0005](0005-deployment-topology-and-client-access.md)
  (Tailscale-based client access, Tailscale-preferred overlay, cloud-side
  authentication termination)

## Context

ADR 0005 planned a phased rollout: Phase 1 with every client device joining a
Tailscale overlay, Phase 2 (cloud entry point) deferred until a mini-program
or multi-tenancy forced it. Phase 1 turned out to have real friction even for
the single-user case:

- **Mobile allows only one active VPN.** Tailscale and proxy tools cannot
  run simultaneously on the owner's phone, so the assistant is unreachable
  whenever the proxy is on.
- Every new device (family members, a new phone, a borrowed browser) needs
  Tailscale installed and joined to the tailnet before it can do anything.
- The tailnet control plane is a third-party dependency on the critical path
  of a personal assistant.

Meanwhile the constraint that shaped ADR 0005 is unchanged: the home
broadband has no public inbound reachability (CGNAT), and the Runtime stays
at home. Reaching it from the public internet therefore still requires a
cloud relay plus an outbound tunnel from the home host.

## Decision

**Add a Gateway layer on the public cloud as the single client entry point.**

```
Client (browser / mobile app, no agent installed)
        │  HTTPS (public IP, v1: no domain)
        ▼
┌───────────────────────────────┐
│  Gateway — Tencent Cloud      │
│  Hong Kong Lighthouse         │
│  nginx: TLS termination,      │
│  reverse proxy, rate limiting │
└──────────────┬────────────────┘
               │  WireGuard point-to-point tunnel
               ▼
        Home host: Runtime (AgentOS, AG-UI) + PostgreSQL
```

1. **Gateway placement**: Tencent Cloud Hong Kong Lighthouse node. Chosen
   for latency and bandwidth quality on the China↔HK path and flat-traffic
   pricing; the node is disposable and replaceable.
2. **Gateway ↔ home link**: a **WireGuard point-to-point tunnel**, not
   Tailscale and not frp. WireGuard is kernel-level, has no third-party
   control-plane dependency, and the home side initiates outbound so it
   works behind CGNAT (with `PersistentKeepalive`). The Gateway's nginx
   proxies to the home host's WireGuard address.
3. **Clients carry nothing**: browsers and mobile apps talk HTTPS to the
   Gateway's public IP. No Tailscale, no VPN, no agent on any user device.
   Tailscale is retired from the access path entirely (server-to-server
   included).
4. **v1 access shape: public IP + HTTPS only.** No domain, no ICP filing.
   TLS is terminated at the Gateway; the certificate strategy for an IP-only
   endpoint (self-signed vs. IP certificate) is an implementation decision
   for the gateway deployment milestone, which is **postponed** — the
   multi-user authentication milestones (v0.6.x) land first and are
   verified over LAN/Tailscale before any public exposure.
5. **Authentication belongs to the Runtime, not the Gateway.** The Gateway
   is a dumb pipe: TLS termination, proxying, rate limiting.
   This supersedes ADR 0005's "the cloud backend terminates user
   authentication" — the trust boundary moves to the Runtime.
   Authentication lands with the **v0.6.x multi-user milestones**, which
   precede the gateway deployment: per-user JWTs issued by an external IdP
   and verified by AgentOS's JWT mode (`Authorization` + verification keys;
   v0.6.0), then per-user data isolation (`user_isolation`; v0.6.1). If the
   gateway is ever deployed before those milestones complete, AgentOS's
   built-in security-key mode (`OS_SECURITY_KEY` env var — one middleware
   covering every route with a constant-time bearer check, `/health` exempt)
   is the interim gate. (Updated 2026-10-19, same-day refinement before
   implementation started.)
6. **The Runtime is still never directly exposed**: no port mapping, no
   public listener on the home host. Its only public reachability is through
   the Gateway's reverse proxy.

What survives from ADR 0005: the foundational principle (clients talk to the
Runtime exclusively via AG-UI over HTTP(S) against a configurable endpoint,
deployment location is a variable), the home-first Runtime placement, the
rejection of DDNS/port-forwarding and Cloudflare Tunnel, and the Phase 3
multi-tenant direction (Gateway evolves into registry + router).

## Alternatives Considered

- **Keep Tailscale for clients (ADR 0005 Phase 1)**: rejected — the mobile
  single-VPN-slot conflict and per-device onboarding friction hit the
  single-user phase already, not just family/public phases.
- **frp reverse tunnel**: rejected — an extra application-layer hop and a
  second component (frps/frpc) to operate for what WireGuard does at the
  kernel level with a single config file per side.
- **Tailscale only between Gateway and home**: rejected — keeps a
  third-party control plane on the critical path for zero benefit over a
  two-node WireGuard config.
- **Cloudflare Tunnel**: rejected (carried over from ADR 0005) —
  inconsistent China connectivity for long-lived SSE streams.
- **Move the Runtime itself to the cloud**: rejected — the Runtime must stay
  co-located with the home network and the future Edge layer; also privacy
  (assistant data stays home).

## Consequences

- **All client devices lose the Tailscale dependency immediately**; the
  mobile VPN conflict disappears.
- **The Runtime is reachable from the public internet (through the
  Gateway)**; exposure is gated from day one by Runtime-side authentication
  (decision 5 — JWT by then, or the security key as interim)
  (decision 5), so unauthenticated requests get 401 before touching any
  agent. Per-user identity and fine-grained authorization remain open until
  the JWT/RBAC milestone.
- A leaked or weak `OS_SECURITY_KEY` is the single point of failure of v1
  auth: it must be a high-entropy random value, live only in the home
  host's `.env`, and rotation means changing the env var and restarting.
- **A new operational dependency**: the Lighthouse node, its WireGuard
  tunnel, and its nginx are on the critical path. When the Gateway or the
  home host is down, all clients are down — same as before, since the
  Runtime was always home.
- **SSE (AG-UI streaming) must survive the proxy + tunnel path**: nginx
  buffering and timeout settings, and WireGuard keepalive, become
  correctness concerns, verified in v0.6.0.
- **TLS without a domain is awkward** (self-signed warnings or IP
  certificates); clients are the owner's own devices in v1, so the trust
  setup cost is small. A domain remains the natural next step.
- The Web UI's thin proxy layer (ADR 0005) can collapse into the Gateway
  nginx; the endpoint-configurable principle is unchanged for clients.
- ADR 0005's phase numbering is moot: the project jumped straight to the
  cloud entry point. Phase 3 (multi-tenant registry/router) remains future
  work on top of the Gateway.
