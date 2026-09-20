# ADR 0002: Single Master Agent as the Only User-Facing Entry

- **Status**: Accepted
- **Date**: 2026-09-19
- **Deciders**: Project owner + architecture discussion

## Context

Spectres is a personal assistant whose core asset is a rich, long-term user
profile. The question arose whether the architecture should allow multiple
Master Agents (e.g., per domain or per channel) or enforce exactly one.

The Master owns the *user relationship*, not capabilities: the single
conversational persona, the unified memory/preference store, and the
authoritative interpretation of user intent. Multiple Masters would fragment
the user profile across separate conversations — precisely the asset the
product exists to build — and would force users to know which agent to address,
leaking architecture into the product experience.

## Decision

There is exactly **one logical Master per user**. This is an architectural
red line: any proposal to add another user-facing agent must be re-examined —
it is almost always a Slave Agent or a Workflow in disguise.

Clarifications of what "one" means:

- **Not a global singleton.** "One" is role uniqueness. In the multi-tenant
  future, instances are created/restored per user (e.g., via `TeamFactory`)
  and scaled horizontally; the role remains singular per user.
- **Not "only one agent works".** Capabilities scale out through Slave
  Agents and nested Teams without limit; only the entry point is unique.
- **Not "no other top-level entities".** Proactive behavior (scheduled
  routines, event reactions) is modeled as scheduler/event-triggered runs of
  the same Master (see ADR 0003) or as deterministic Workflows — never as a
  second user-facing agent.

## Alternatives Considered

- **Multiple domain Masters** (fitness assistant, home assistant, ...):
  rejected — fragments the user profile and the conversational persona;
  domain specialization belongs to Slaves.
- **Per-channel Masters** (web, app, voice): rejected — channels are
  interfaces to the same Master, not separate agents.

## Consequences

- All user traffic converges on one Master, which is a bottleneck and a
  context-growth risk by design. Mitigations: `route` mode or direct Master
  answers for trivial requests; nested Teams when domains grow.
- The Master's model must be strong enough for intent arbitration and
  delegation decisions; Slaves may use cheaper or more specialized models.
- Memory consolidation has a single owner, simplifying the future Mem0 /
  Hindsight integration.
