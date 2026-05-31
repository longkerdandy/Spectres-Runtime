# User Profile Management — Architecture & Design

**Status:** design stage, **high-level**. Version-independent. This document fixes
the durable *positioning and shape* of the Profile Management component. Concrete
technical details — schema, storage layout, API surface — are intentionally left
out and will be refined (and are expected to change) during implementation.

It is a component-level design under the Runtime-wide architecture in
[`Agents.md`](../../Agents.md). Its first consumer is the
[Recipe Agent](./recipe-agent.md) (see its §4); future agents (health, shopping)
are expected consumers.

---

## 1. Positioning

Profile Management is a **Runtime-level shared component**, not owned by any single
agent. It is the system of record for *who the user is* — durable, structured facts
about users and their households — and serves them to agents through a
framework-neutral interface.

- **Shared, not per-agent.** User identity and household data are inherently
  cross-agent; modeling them inside one agent would silo the data and force
  duplication. Agents are *consumers*.
- **Facts, not capability.** The component stores and serves facts; interpreting
  them (e.g. nutrition reasoning) belongs to the consuming agent's capability
  layer, per the Facts-vs-Capability principle.
- **We own it.** Built as our own component rather than adopting a framework's
  per-user profile, so it is not bound to any one agent framework's data model or
  scope.

---

## 2. Core Model

Two first-class entities and their membership relation:

- **User** — an individual person.
- **Household** — a group of users who eat / plan together; a user may belong to a
  household. Aggregation across members (e.g. combined dietary constraints) is a
  first-class operation, not an afterthought.

Exact fields and relations are deliberately left to implementation.

---

## 3. Two Data Shapes

User information comes in two shapes with different access patterns; the component
serves both:

| Shape | Holds | Access |
|---|---|---|
| **Key-value (current state)** | Stable facts — dietary restrictions, dietary style, chronic conditions, long-term goals | Exact recall; updated in place |
| **Time-series** | Changing measurements — weight, blood glucose, blood pressure | Append-only, timestamped; read as latest value / trend / range |

**Context discipline:** time-series data is never served in full into an agent's
prompt — only a latest value plus a short trend summary (the same "keep context
small" rule the Runtime applies to retrieval).

---

## 4. How Agents Consume It

The primary integration is framework-neutral (the chosen approach):

- **Deterministic injection.** Must-have constraints (and key health snapshots) are
  injected into an agent run via a pre-run `dependencies` callback — reliable, not
  dependent on the model choosing to look them up.
- **On-demand tools.** Deeper detail and writes (e.g. record a measurement, fetch a
  specific member) are exposed as function tools the agent calls when needed.
- **Household aggregation.** A single call returns the merged view of a household's
  members, so an agent can plan "for the table" without stitching profiles itself.

An adapter to a framework's native learning-store protocol (e.g. an Agno custom
store) is an **optional future compatibility layer**, not the primary interface.

> Soft, unstructured preferences ("likes spicy") are intentionally **out of scope**
> here — they stay in the consuming agent's memory store (e.g. Agno User Memory).

---

## 5. Writes & Auto-Extraction

- **Explicit / confirmed writes first.** Profile data — especially safety- or
  health-relevant fields — is written explicitly or via confirmed agent actions,
  not silently inferred.
- **Auto-extraction is deferred.** Automatically extracting profile facts from
  conversation (cf. Agno's *always* / *agentic* modes) is a later phase. When
  added, it lands as a post-processing step calling this component and keeps the
  explicit-confirmation bar for safety-relevant fields.

---

## 6. Out of Scope / Later

- Concrete schema, storage layout, and API surface (not fixed at this stage).
- Automatic extraction from conversation.
- Authentication / RBAC / per-field access control.
- Sharing and permissions beyond the household grouping.
- Sync to Edge / Client.

---

> **Runtime-plan note.** Introducing a real, evolving profile + time-series schema
> is likely to bring a migration framework (e.g. Alembic) forward earlier than the
> recipe plan's initial "single schema-creation step" assumption.
