# ADR 0005: Deployment Topology and Client Access Paths

- **Status**: Accepted
- **Date**: 2026-09-19
- **Deciders**: Project owner + architecture discussion

## Context

The Runtime (AgentOS) will run at home on a Windows host, co-located with the
future Edge layer. The Web UI was initially assumed to be cloud-hosted, which
posed the question of how a cloud frontend reaches a Runtime behind home NAT
(carrier-grade NAT, no public inbound ports, dynamic IP — typical for
residential broadband in China).

Working through the tunnel options (Tailscale/WireGuard overlay, frp reverse
tunnel, Cloudflare Tunnel, message queue) surfaced a deeper insight: once
clients enter through an overlay network, the cloud server is optional for the
single-user phase — the entire stack can live at home.

What forces a cloud entry point eventually:

1. **WeChat mini-programs** cannot join an overlay network; they require a
   public HTTPS endpoint (with ICP filing in China). The roadmap includes a
   mini-program client.
2. Access from arbitrary devices/browsers without an installed agent.
3. Multi-tenancy — other users cannot join the owner's tailnet.

High availability is *not* a reason: the Runtime lives at home, so a cloud UI
without the home Runtime is an empty shell.

## Decision

**Foundational principle — deployment location is a variable, not an
architecture decision.** Every client (Web, mobile app, mini-program) talks to
the Runtime exclusively via **AG-UI over HTTP(S) against a configurable
endpoint**. No client assumes where it or the Runtime is deployed. The Web
UI's thin proxy layer must be separable from its static frontend, because the
proxy must sit in the cloud for mini-program/multi-tenant scenarios while it
can live at home during the self-hosted phase.

**Phase 1 (single user) — full home stack + Tailscale.**

- Web UI, Runtime, PostgreSQL, and Edge all run on the home Windows host.
- The owner's devices (laptop, phone) join the tailnet and access services via
  their `100.x` addresses; no cloud server, no public exposure, no DDNS.
- Benefits: maximum privacy (assistant data never leaves home), zero cloud
  cost, one deployment unit, one less network hop.

**Phase 2 — cloud entry point when forced.**

When a mini-program, arbitrary-device access, or external users are needed:
move the Web UI (or only its proxy layer) to a cloud VPS; the Runtime stays
home and connects outbound through the overlay (Tailscale, preferred) or an
frp reverse tunnel. The Runtime is **never** publicly exposed and never uses
port mapping; the cloud backend terminates user authentication and proxies
AG-UI (SSE) to the home Runtime, adding a service credential (shared secret /
JWT; AgentOS RBAC scopes can enforce it).

**Phase 3 — multi-tenant.** The cloud backend evolves into a registry +
router: each home Runtime registers its identity and tunnel address on
startup, and the proxy routes by `user_id`. The interface shape is designed
for this from day one but implemented with a single entry.

**Mobile app access paths** (same endpoint-configurable principle):

| Stage | Path |
|-------|------|
| Self-use | Official Tailscale app on the phone. Caveat: iOS/Android allow only **one active VPN** — Tailscale and proxy tools (e.g., Shadowrocket) cannot run simultaneously, unlike on desktop |
| Family / small circle | Embed `tsnet` in the app (the app itself becomes a tailnet node, no system VPN slot consumed), or move to the cloud entry early |
| Public release | Cloud entry, shared with the mini-program |

**Implementation notes.**

- *Clash Verge TUN coexistence* (owner's laptop, and the home host if it runs
  a proxy): Clash TUN captures all traffic, so exclude the tailnet:
  `tun.route-exclude-address: [100.64.0.0/10]`, a
  `IP-CIDR,100.64.0.0/10,DIRECT,no-resolve` rule, and `+.ts.net` in
  `dns.fake-ip-filter`. Tailscale's exit-node feature must stay off. The home
  server should preferably run no Clash at all to keep its network path simple.
- *Windows host operations*: Runtime runs natively on Python; PostgreSQL via
  Docker Desktop (same as dev). Register Docker Desktop, Tailscale/frpc, and
  the Runtime as auto-starting services (Task Scheduler / NSSM); configure
  power settings so the host never sleeps.

## Alternatives Considered

- **DDNS + port forwarding**: rejected — CGNAT and ISP inbound blocking make
  it unreliable, and it exposes the home network.
- **Cloudflare Tunnel**: rejected for this deployment — connectivity quality
  from China is inconsistent for long-lived SSE streams.
- **Cloud-hosted Web UI from day one**: deferred — adds cost and a proxy hop
  with no user value in the single-user phase; the endpoint-configurable
  principle keeps the move trivial when it becomes necessary.
- **Browser directly reaches the home Runtime**: rejected — would force the
  Runtime to handle public authentication and enlarge its attack surface; the
  cloud/edge proxy is the trust boundary.

## Consequences

- v0.3.0 and near-term milestones require **no deployment work**; networking
  lands when the Web UI project starts or a public entry becomes necessary.
- The Runtime codebase is unaffected by deployment topology — the payoff of
  standardizing on AG-UI between Client and Runtime.
- The owner's own devices carry the Tailscale dependency; onboarding family
  members has a real (small) setup cost until Phase 2.
