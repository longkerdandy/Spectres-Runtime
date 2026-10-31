# Architecture Decision Records

This directory records significant architecture decisions for Spectres
Runtime. Each ADR captures the context, the decision, the alternatives
considered, and the consequences **at the time the decision was made**.

## Conventions

- ADRs are **immutable** once accepted. If a decision is revisited, write a
  new ADR that supersedes the old one, and mark the old one's status as
  `Superseded by ADR NNNN`.
- File name: `NNNN-short-kebab-title.md`, numbered sequentially.
- Format: Status / Date / Deciders, then Context → Decision → Alternatives
  Considered → Consequences.
- The **current state of the system** lives in
  [`../architecture/`](../architecture/README.md), not here. ADRs explain *why*;
  the architecture document explains *what is*.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-agno-team-as-multi-agent-foundation.md) | Adopt Agno Team as the Multi-Agent Foundation | Accepted |
| [0002](0002-single-master-agent.md) | Single Master Agent as the Only User-Facing Entry | Accepted |
| [0003](0003-automation-trigger-layers-and-session-isolation.md) | Automation Triggers — Layered Handling and Session Isolation | Accepted |
| [0004](0004-ag-ui-team-visibility-strategy.md) | AG-UI Visibility Strategy for Agent Teams | Accepted |
| [0005](0005-deployment-topology-and-client-access.md) | Deployment Topology and Client Access Paths | Partially superseded by 0008 |
| [0006](0006-web-search-tool-tavily.md) | Web Search Tool — from ddgs Meta-Search to Tavily | Accepted |
| [0007](0007-scheduled-tasks-agno-scheduler.md) | Scheduled Tasks — Agno Built-in Scheduler, Deterministic-Only MVP | Accepted |
| [0008](0008-cloud-gateway-public-entry.md) | Cloud Gateway as the Public Entry Point | Accepted |
| [0009](0009-idp-logto-self-hosted.md) | Identity Provider — Logto OSS Self-Hosted | Accepted |
| [0010](0010-logto-rbac-agno-jwt-scopes.md) | Authorization — Logto RBAC with Agno JWT Scopes | Accepted |
