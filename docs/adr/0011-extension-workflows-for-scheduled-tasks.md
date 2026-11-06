# ADR 0011: Extension Workflows for Scheduled Tasks

- **Status**: Accepted
- **Date**: 2026-11-04
- **Deciders**: Project owner + architecture discussion

## Context

ADR 0007 adopted Agno Scheduler with extension REST routes as deterministic
MVP targets. That choice intentionally avoided Workflows for simple tasks and
kept one composite ETF Grid schedule that synchronized shared data before
recomputing every ledger owner's signals.

User-managed schedules change the requirements. Agno's native schedule create,
update, enable, and trigger routes allow an ordinary user to target a component
run endpoint only when that user has the matching run scope. Non-run extension
HTTP endpoints are admin-only targets. A parallel Runtime Action abstraction or
custom schedule API would duplicate framework behavior and ownership rules.

The product now requires extension-provided one-step and sequential multi-step
operations, native schedule CRUD, a single automatic system data-sync schedule,
and user-created ETF Grid recompute schedules. Independent sync and recompute
schedules do not need a strict execution order, and existing users must not
receive automatically created personal schedules.

## Decision

1. **Use Agno Workflow directly as the extension execution contribution.**
   `ExtensionContribution` gains `workflows`, and Runtime passes the flattened
   list to `AgentOS(workflows=...)`. No Action wrapper, action registry,
   generic action dispatcher, custom schedule router, or custom scheduler is
   introduced.
2. **Use native component run targets for user-managed schedules.** ETF Grid
   provides `etf_grid_data_sync` and `etf_grid_recompute` deterministic
   Workflows. Personal schedules target `/workflows/etf_grid_recompute/runs`;
   Agno derives the Workflow owner from the verified schedule owner. The
   ordinary role receives `workflows:read` and resource-level
   `workflows:etf_grid_recompute:run`, not wildcard Workflow run permission.
3. **Register only the system data-sync schedule automatically.** The sole
   unowned `etf_grid_daily_sync` schedule targets `etf_grid_data_sync`. Runtime
   does not create, migrate, or delete personal recompute schedules.
4. **Accept independent execution.** Sync and recompute have no dependency or
   strict ordering. Recompute uses the latest shared data persisted when its
   own schedule runs. Cross-schedule dependencies and completion-triggered
   fan-out remain future work.
5. **Retain Agno-native management and history.** Schedule CRUD,
   enable/disable, manual trigger, run history, Workflow runs, ownership,
   retries, and linked output remain framework-managed. The previous composite
   `/refresh` route may remain an explicit admin/internal manual operation but
   is no longer a scheduled target.

ADR 0007's decisions to use Agno Scheduler, preserve deterministic idempotent
execution, and avoid custom scheduling infrastructure remain in force. Its
MVP-specific rejection of Workflow carriers for deterministic tasks is
superseded for extension-contributed scheduled operations.

## Alternatives Considered

- **A lightweight Action registry plus generic HTTP executor**: would make
  simple functions concise, but native schedule writes reject ordinary-user
  non-run HTTP targets. Supporting the required product flow would need custom
  write APIs and target authorization, duplicating Agno behavior. Rejected.
- **Keep direct extension REST targets**: works for code-registered admin or
  system schedules but cannot support ordinary-user CRUD under native Agno
  permissions. Rejected for personal recompute.
- **One generic Action Workflow dispatching to a function registry**: preserves
  native run endpoints but adds an unnecessary registry and hides the Action
  catalog inside payload data. Rejected in favor of explicit Workflow ids.
- **Automatically migrate existing users to personal recompute schedules**:
  would preserve old fan-out behavior but violates the confirmed user-managed
  ownership model. Rejected.
- **Add schedule dependencies or sync-completion fan-out**: unnecessary because
  the owner accepted independent execution. Deferred until a real freshness or
  ordering requirement appears.

## Consequences

- Extensions can provide one-step or sequential multi-step deterministic
  operations without a Runtime-specific execution abstraction.
- Workflow runs and sessions become part of scheduled execution history;
  schedule-run rows retain their parent owner and link to Workflow run output.
- Personal recompute schedules disappear only when their owner deletes them;
  Runtime startup never recreates them. Removing the old automatic fan-out
  means users must create a schedule if they want recurring recompute.
- Sync and recompute can overlap or run in either order. Each operation must be
  idempotent and tolerate the latest available persisted inputs.
- Logto role changes affect newly issued tokens. Administrators must add the
  native Workflow read and resource-level recompute-run permissions to the
  ordinary role; wildcard run permission would expose system sync and is not
  allowed.
- Future agent-bearing Workflows can use the same scheduler carrier, but no
  agent, notification, dependency, or SchedulerTools functionality is implied
  by this decision.
