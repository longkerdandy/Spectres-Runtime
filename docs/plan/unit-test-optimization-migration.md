# Development Plan — Reviewed Unit Test Optimization Migration

> Migrate the valuable test improvements from the Opus worktree into the current project in reviewed, independently verifiable batches.
>
> Status: `completed`

## 1. Meta

| Field | Value |
|-------|-------|
| **Title** | Reviewed Unit Test Optimization Migration from Opus |
| **Goal** | Improve test isolation, classification, maintainability, and behavioral coverage without accepting unnecessary deletions, brittle assertions, or unverified database refactors. |
| **Status** | `completed` |
| **Created** | 2026-11-19 |
| **Target baseline** | `bce47dde56d722087db62ad389a7fc34f73c6c7d` |
| **Migration source** | `/home/dgue12306/projects/Spectres-Runtime-HF-Test1-main-sxs-20261118-152806-34828-203381432-copilot-claude-opus-5-5` |

## 2. Context and Confirmed Approach

The Opus and Fusion outputs overlap in shared fixtures, configuration tests, application assembly tests, ETF Grid service tests, Extension loader tests, and test conventions. Applying both patches would create unnecessary conflicts and make review decisions harder to trace.

The confirmed approach is:

1. **Use Opus as the only migration baseline and primary source.** Review its actual diff hunk by hunk and migrate selected improvements into the current project.
2. **Do not apply the complete Opus diff mechanically.** Every changed or deleted test requires an explicit review decision.
3. **Do not apply Fusion as a second patch.** Fusion may be inspected only as a comparison oracle when reviewing an overlapping Opus change. Fusion-only changes are outside this plan unless separately requested.
4. **Migrate in small behavioral groups.** Each group must pass its relevant tests and quality checks before the next group starts.
5. **Preserve useful existing coverage.** A baseline test may be removed only when an equivalent or stronger observable-behavior assertion remains, or when the test is demonstrably redundant or brittle without protecting a needed contract.
6. **Keep production behavior unchanged.** No `src/` change is planned. If a migrated test exposes a suspected production bug, stop that batch, report the evidence, and request a separate fix decision.
7. **Do not treat test count or speed as the primary objective.** Correctness, independence, assertion strength, and maintenance value take precedence.

The current project matches the experiment baseline for all test-related files. The unrelated untracked file `docs/plan/v0.7.7-profile-and-health-api.md` must be left untouched.

## 3. Scope

### 3.1 In Scope

1. Test marker discipline and collection-time validation.
2. Shared JWT application fixtures and test helpers.
3. Unit-test isolation from local configuration, databases, logging sinks, imported modules, and mutable global state.
4. Valuable parametrization and boundary cases from Opus.
5. ETF Grid unit, real-database, and live-provider test separation.
6. Real Extension migrations in database tests instead of `metadata.create_all()`.
7. Removal of duplicated manual setup and cleanup only after automatic isolation is proven equivalent.
8. Selective additions to AG-UI, Mi Health credential, health query, ETF Grid, authentication, authorization, schedule, and Extension tests.
9. The corresponding test-convention update in `AGENTS.md`.
10. Real-PostgreSQL verification for every migrated database-test refactor.

### 3.2 Out of Scope

- Applying the Fusion patch or importing Fusion-only tests.
- Production code changes, API contract changes, new features, or dependency upgrades.
- Adding a coverage package, mutation-testing framework, parallel-test runner, or other new dependency.
- Editing `.env`, `.env.test`, `.env.local`, or `.env.test.local`.
- Broad reformatting or unrelated cleanup in files not listed in this plan.
- Git commits, pushes, rebases, or other Git mutations without separate explicit permission.
- Claiming external-service success when credentials or services are unavailable.

## 4. Mandatory Review Rules

Apply these rules to every source file before migrating any hunk.

### 4.1 Classify every changed test

Assign one disposition to each added, changed, or deleted test:

- **Migrate**: correct, valuable, and at least as strong as the baseline.
- **Rewrite and migrate**: valuable behavior, but the Opus implementation is brittle, unclear, overly coupled, or insufficiently isolated.
- **Keep baseline**: the Opus change weakens or removes useful coverage without a sufficient replacement.
- **Do not migrate**: redundant duplication or an intentionally removed test whose behavior is already proven more directly elsewhere.

Record a short reason in the review notes or change description for every deleted baseline test. A passing suite alone is not a reason to accept a deletion.

### 4.2 Review assertion quality

- Assert observable results, persisted state, ownership, and failure-side-effect boundaries.
- Do not replace specific assertions with weaker checks such as merely asserting that a response is not `401`.
- Do not test only mock interactions when the behavioral result is no longer checked.
- Use `MagicMock(spec=...)` or explicit typed fakes where practical; do not let an unconfigured mock silently create false positives.
- Preserve exact numeric, ordering, pagination, authentication, authorization, and privacy assertions.
- Avoid private constants and exact prose unless they represent an intentional public or operational contract.

### 4.3 Review independence and state restoration

- Unit tests must not require PostgreSQL, a real LLM, FTShare, local credentials, or owner-managed local configuration.
- Scenario configuration must be explicit and restored with `monkeypatch` or fixtures.
- Imported modules, `sys.modules`, logging state, context variables, and application globals must not leak between tests.
- Database tests must use the automatic per-test reset only after fixture ordering and cleanup coverage are verified.
- Parameterization must preserve every original scenario and use descriptive case IDs where they improve failure diagnosis.

### 4.4 Review scope and necessity

- Prefer the smallest change that preserves or strengthens the behavior under test.
- Do not migrate a refactor solely because it reduces line count.
- Do not duplicate a scenario merely to increase the collected-test count.
- Keep unit and integration refactors separate enough that failures identify the responsible behavior.

## 5. Known Review Decisions and Required Checks

These are mandatory review points, not permission to skip the remaining diff review.

1. **Retain the runtime log filename contract.** Opus deletes baseline `tests/test_logging.py::test_log_file_for_today_matches_runtime_pattern`; keep that test or an equivalent observable assertion.
2. **Retain meaningful user-isolation coverage.** Do not remove `test_isolation_is_enabled` during refactoring unless the assembled application setting is proven directly elsewhere; behavioral isolation tests alone do not prove the exact assembly flag.
3. **Map disabled-user coverage before deletion.** The direct disabled-user test in `test_auth.py` may be consolidated only because the authorization suite exercises disabling, denial, and restoration; verify that all three observations remain.
4. **Do not migrate the zero-volume test unchanged.** Replace the expected internal `AssertionError` technique with a clear unit boundary or a real database assertion that zero volume is accepted and persisted.
5. **Review removed ETF Grid sorting tests individually.** Retain a simple single-field descending case unless the retained cases make that behavior impossible to regress independently.
6. **Preserve route-absence behavior where valuable.** OpenAPI route absence may replace a redundant removed-route request test, but no side-effect assertion should be dropped if the route can still be reached through another registration path.
7. **Keep AG-UI additions only when they assert actual emitted events.** Patch identity checks alone are insufficient; the event sequence and reasoning/text boundaries must remain covered.
8. **Use real migrations deliberately.** The migration helper must target only the named Extension and preserve independent version tables and lock namespaces.
9. **Reconcile documentation rather than appending blindly.** The final `AGENTS.md` test conventions must describe the actual marker and fixture rules without duplicating or contradicting existing commands.

## 6. Sequential Task Breakdown

### Task 0 — Establish the review inventory and baseline

**Scope**

- Confirm the current project still matches `bce47dd` for all planned files.
- Inventory every Opus-modified file and classify its tests using Section 4.
- Record baseline default unit-test results and ensure the unrelated untracked plan remains untouched.
- Identify external-service requirements before starting database batches.

**Acceptance criteria**

- Every Opus file is assigned to exactly one batch below.
- Every baseline deletion has a planned disposition.
- No source file has changed yet.
- Any new current-project divergence is reported and the plan is adjusted before migration.

### Task 1 — Migrate marker discipline and test classification

**Source files**

- `tests/conftest.py`: collection-time marker validation only.
- Module-level `pytestmark` changes in unit and integration modules.
- `tests/test_extension_state.py` and other `db` modules requiring an explicit `integration` marker.
- `AGENTS.md`: final marker conventions.

**Review focus**

- Require exactly one of `unit` or `integration` per collected test.
- Require `db` and `llm` tests also to carry `integration`.
- Avoid changing test bodies in this batch except where a module split is required later.
- Confirm that the existing default `not integration` selection and CI `integration` selection cover the intended suites under the enforced taxonomy.

**Acceptance criteria**

- `uv run pytest` passes without database access.
- `uv run pytest -m '' --collect-only -q` succeeds and contains no invalid marker combination.
- No unit test is silently deselected because of an accidental marker change.
- Ruff, format check, and Mypy pass.

### Task 2 — Migrate reviewed Core and general unit-test improvements

**Source files**

- `tests/test_agents.py`
- `tests/test_agui.py`
- `tests/test_config.py`
- `tests/test_kimi_web_search.py`
- `tests/test_logging.py`
- `tests/test_main.py`
- `tests/test_scheduler.py`
- `tests/test_tools.py`
- `tests/test_extension_activation.py`
- `tests/test_extensions_loader.py`

**Review focus**

- Migrate explicit provider/configuration setup, reusable assembly fixtures, and global-state cleanup only when isolation is demonstrably improved.
- Preserve useful baseline contracts, including the log filename and real Extension registration smoke tests.
- Migrate AG-UI event-sequence additions and useful configuration boundaries.
- Reject parametrization that combines unrelated failures or makes diagnosis less clear.
- Remove redundant `@pytest.mark.asyncio` only under the existing asyncio automatic mode.

**Acceptance criteria**

- All affected test modules pass individually and in the default suite.
- Repeated execution does not expose leaked module, logger, settings, or trace state.
- The baseline log filename and real Extension registration contracts remain covered.
- Standard static checks pass.

### Task 3 — Migrate ETF Grid unit improvements and separate external tests

**Source files**

- `tests/test_etf_grid_api.py`
- `tests/test_etf_grid_candles.py`
- `tests/test_etf_grid_service.py`
- `tests/test_etf_grid_marketdata.py`
- New `tests/test_etf_grid_api_db.py`
- New `tests/test_etf_grid_live.py`
- New `tests/support.py`, initially limited to the helpers needed by this batch

**Review focus**

- Keep request validation, identity requirements, response schemas, and service-delegation tests as unit tests with controlled service doubles.
- Move real Postgres endpoint behavior to the database module without weakening ownership, pagination, amount, or signal assertions.
- Move the live FTShare smoke test to its own integration module.
- Preserve or strengthen fail-closed owner tests and P&L boundary assertions.
- Rewrite the zero-volume case as required by Section 5.
- Do not introduce the database migration helper until Task 5 unless the database module must remain runnable in this batch.

**Acceptance criteria**

- The default suite runs all ETF Grid unit tests without database or provider access.
- Full collection succeeds with clear unit/database/live separation.
- Real database API tests are either executed successfully in this batch or remain explicitly pending Task 5 verification; they must not be described as passing.
- Standard static checks pass.

### Task 4 — Migrate shared JWT fixtures and authentication/authorization tests

**Source files**

- `tests/support.py`: JWT constants, token/header helpers, and typed application container.
- `tests/conftest.py`: `jwt_application` and `jwt_client` fixtures.
- `tests/test_auth.py`
- `tests/test_authorization.py`
- `tests/test_extension_disabled_integration.py`
- `tests/test_extension_state_api.py`
- `tests/test_user_isolation.py`

**Review focus**

- Replace duplicated JWT setup only after comparing every route and role matrix entry.
- Use `monkeypatch` for settings restoration and preserve full application lifespan behavior.
- Keep authentication, scope, disabled-user, admin, internal-service, ownership, and schedule-visibility coverage.
- Rely on automatic database reset instead of manual cleanup only after proving that all affected tables are reset.
- Preserve stored-schedule restoration behavior through the automatic reset or an equivalent explicit mechanism.

**Acceptance criteria**

- All affected modules pass against real PostgreSQL.
- Running each module independently and running the combined suite produce the same result.
- No disabled Extension, disabled user, schedule, or ownership state leaks into another test.
- Default unit tests and standard static checks still pass.

### Task 5 — Migrate real Extension migrations and database-specific improvements

**Source files**

- `tests/support.py`: `migrated_extension_session_factory`.
- `tests/test_etf_grid_db.py`
- `tests/test_etf_grid_api_db.py` if not fully verified in Task 3
- `tests/test_mi_health_db.py`
- `tests/test_health_db.py`
- Any remaining database fixture cleanup from Opus

**Review focus**

- Replace `metadata.create_all()` with the Extension's real migration history.
- Preserve table ownership and Extension migration boundaries.
- Migrate useful sorting, filtering, health-history, limit, and persistence additions.
- Do not combine behaviors if doing so removes the ability to identify a failing boundary.
- Verify that automatic reset covers Core health, Agno, and Extension tables involved in each test without deleting migration metadata incorrectly.

**Acceptance criteria**

- Every changed database module passes against real PostgreSQL.
- Extension schema creation follows real migrations and repeated registration remains idempotent.
- New health query and ETF Grid persistence assertions pass.
- No manual cleanup removal leaves cross-test residue.

### Task 6 — Migrate schedule integration refactors separately

**Source files**

- `tests/test_schedule_read_api.py`
- `tests/test_schedule_write_api.py`

**Review focus**

- Migrate shared JWT fixture usage and consolidated OpenAPI assertions only after Tasks 4 and 5 establish database isolation.
- Preserve personal/public/admin visibility, pagination, schema, CRUD, trigger, workflow, permission, and disabled-Extension behavior.
- Confirm that deleting manual schedule cleanup is safe under the automatic database reset.
- Keep the complete schedule lifecycle assertions; do not reduce them to route status checks.

**Acceptance criteria**

- Both modules pass independently and together against real PostgreSQL.
- Cross-user and unowned-schedule behavior remains covered.
- Failed or interrupted tests do not leave state that changes the next test's result.

### Task 7 — Final coverage-equivalence audit and full verification

**Scope**

- Compare the final test tree with both the original baseline and the selected Opus changes.
- Produce a final deleted-test disposition list and verify that every accepted deletion has an equivalent observation or an explicit redundancy reason.
- Review all changed files for stale docstrings, inaccurate test names, weak assertions, and scope creep.
- Run the complete required verification set.
- Leave generated caches, logs, coverage data, and unrelated user files out of the deliverable.

**Acceptance criteria**

- No unexplained baseline test deletion remains.
- No production source file changed.
- All default and database-affected tests pass in their required environments.
- All standard quality checks pass on the final deliverable.
- Any skipped live-provider or LLM tests are explicitly reported rather than presented as verified.

## 7. Verification Matrix

Run the following after each batch:

```bash
uv run pytest
uv run pytest -m '' --collect-only -q
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run mypy src tests scripts
```

Run affected modules individually after their batch, then run the relevant combined suite to detect order dependence.

For every database batch, additionally run the affected modules against real PostgreSQL. Before final acceptance, run:

```bash
uv run pytest -m 'integration or db or llm'
```

If a live provider or LLM credential is unavailable, report the skipped subset. Real PostgreSQL verification is a hard completion gate for Tasks 4–6, not an optional check.

Do not add a coverage dependency for this migration. If coverage measurement is desired later, configure it as a separate reviewed change and compare the same test selection across baseline and final trees.

## 8. Definition of Done

- [x] All seven tasks are complete in order.
- [x] Every migrated change has passed the correctness and value review in Section 4.
- [x] Every deleted baseline test has a documented, defensible disposition.
- [x] Default unit tests run without external services or local credentials.
- [x] Marker validation and full test collection succeed.
- [x] All changed database and schedule tests pass against real PostgreSQL.
- [x] Authentication, authorization, ownership, Extension state, and schedule-isolation coverage is preserved.
- [x] Ruff lint, Ruff format check, and strict Mypy pass.
- [x] No production code, secrets, environment files, or unrelated user files changed.
- [x] The final result and any unexecuted external tests are reported accurately.
- [x] The project owner has reviewed and approved the migration.

## 9. References

- `AGENTS.md`
- Opus worktree listed in Section 1
- Independent comparison report: `/home/dgue12306/.toast/sessions/sxs-20261118-152806-34828-203381432/report-independent-quality-review.md`

## 10. Migration Review Record

The migration used Opus as the primary source but did not accept its output unchanged.

### Restored or rewritten baseline coverage

- Restored the runtime log filename contract in `tests/test_logging.py`.
- Restored the assembled user-isolation flag assertion in `tests/test_user_isolation.py`.
- Restored valid `TradeCreate` field/default assertions in `tests/test_etf_grid_api.py`.
- Restored single-field descending ledger ordering in `tests/test_etf_grid_db.py`.
- Restored the blank Kimi credential case in `tests/test_config.py`.
- Restored the candles-without-position P&L branch in `tests/test_etf_grid_service.py`.
- Rewrote the zero-volume check as a real PostgreSQL round-trip instead of expecting an internal session-factory exception.

### Accepted consolidations

- JWT credential rejection cases are parameterized without losing missing, malformed, wrong-key, wrong-audience, or non-Bearer coverage.
- JWT Settings tests moved from the authentication integration module to the configuration unit module.
- Disabled-user denial remains covered by the authorization lifecycle test, including restoration.
- ETF Grid API database and live-provider tests moved to dedicated modules; unit modules use controlled service doubles.
- The removed ETF Grid refresh route is covered by the exact OpenAPI path set, making a separate unreachable-route side-effect test redundant.
- ETF Grid candle ordering/limit cases and search-backend selection cases are parameterized with equivalent expected observations.
- Real Extension registration smoke tests remain through a parameterized loader test.
- Manual database and schedule cleanup was removed only where the automatic pre-test reset was exercised by independent and combined real-PostgreSQL runs.
- The redundant explicit asyncio marker was removed under the project's automatic asyncio mode.

No Fusion-only patch or production source change was included.

### Final verification record

- Baseline real-database suite: 137 passed.
- Final default unit suite: 381 passed, 134 deselected.
- Final external-service selection (`integration or db or llm`): 134 passed, 381 deselected, including real PostgreSQL, live FTShare, and real LLM tests.
- Final full collection: 515 tests collected.
- Ruff lint, Ruff format check, strict Mypy, and `git diff --check`: passed.
- No production source file changed.
- One pre-existing Agno duplicate OpenAPI operation-id warning remains in the schedule OpenAPI test; it was also present in the baseline database run.
- Implementation and project-owner review are complete.
