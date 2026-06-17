# Milestone Plan Template

> Canonical plan for a single milestone. Write this before writing code. Review it with the user, then execute task by task.
>
> Save as: `docs/plan/milestones/{version}/milestone.md`

---

## 1. Meta

| Field | Value |
|-------|-------|
| **Milestone** | `{version}` e.g. `v0.1.0` |
| **Title** | Short, descriptive title |
| **Goal** | One-sentence outcome this milestone delivers |
| **Status** | `draft` / `review` / `approved` / `in-progress` / `completed` |

---

## 2. Context

What this milestone addresses and what the agent should know before starting.

- Read first: `AGENTS.md`, `docs/plan/project.md`, and relevant prior milestone plans.
- Prior dependencies: list any milestones that must be completed first.
- Key constraints or decisions that affect implementation.

---

## 3. Scope

### 3.1 In Scope

Concrete deliverables for this milestone. Each item should be implementable and testable.

1. **Deliverable 1**
   - What to build
   - Boundaries
2. **Deliverable 2**
   - ...

### 3.2 Out of Scope

Deliberately excluded items to prevent scope creep.

- Feature or task 1
- Feature or task 2

---

## 4. Success Criteria

Verifiable conditions for "done". Use checkboxes.

- [ ] Criterion 1
- [ ] Criterion 2
- [ ] Criterion 3

---

## 5. Task Breakdown

Small, sequential or parallel tasks. Each task must have clear acceptance criteria.

| ID | Task | Priority | Depends On | Acceptance Criteria |
|----|------|----------|------------|---------------------|
| 1 | Task description | High | - | What must be true for this task to be done |
| 2 | Task description | Medium | 1 | ... |

---

## 6. Definition of Done

The milestone is complete when:

- [ ] All tasks in Section 5 are done.
- [ ] All success criteria in Section 4 are met.
- [ ] Quality checks (lint, typecheck, tests) pass.
- [ ] User has reviewed and approved the result.
- [ ] No secrets or generated artifacts are committed.

---

## 7. References

- `AGENTS.md`
- `docs/plan/project.md`
- Prior milestone plans
- External documentation or decision records
