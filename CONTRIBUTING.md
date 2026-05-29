# Contributing

Working conventions for this repository. Architecture lives in
[`Agents.md`](./Agents.md); environment / commands / troubleshooting in
[`docs/environment.md`](./docs/environment.md).

## Commit messages

**[Conventional Commits 1.0](https://www.conventionalcommits.org/en/v1.0.0/)**,
enforced by the `commit-msg` git hook (and, planned, by a PR-title CI check).

Shape: `type(scope)?!?: subject`

- **type** (required, one of): `feat`, `fix`, `docs`, `style`, `refactor`,
  `perf`, `test`, `build`, `ci`, `chore`, `revert`
- **scope** (optional, lowercase): `agent`, `memory`, `knowledge`, `edge`,
  `auth`, `ci`, `deps`, `docs`, …
- **`!`** after type/scope marks a breaking change
- **subject**: imperative, lowercase, no trailing period, ≤ ~50 chars
- **body** (optional): blank line after subject, wrap ~72 chars, explain
  *what* and *why*
- **footer** (optional): `BREAKING CHANGE: …`, `Refs: #123`, `Closes: #123`

Examples:

```text
feat(agent): add agentfactory contract
fix(memory): handle empty session id
feat(api)!: drop legacy /v0 endpoint
chore(deps): bump fastapi to 0.137.0
```

Only the type/shape/non-empty-subject rules are machine-enforced; the rest
are project conventions — honour them so `git log` stays readable.

## Branching

**Trunk-based.** A single long-lived branch — `main`. All work lands on
`main` directly. Short-lived topic branches are optional, used only when an
experiment is large enough to want isolation; merge back via fast-forward
or squash.

- **Releases:** annotated tags on `main`.
  `git tag -a v0.1.0 -m "v0.1.0" && git push --tags`. No `release/*` branch.
- **Hotfixes:** normal commits on `main`, tagged with a new patch version.
  No `hotfix/*` branch.
- **`main` protection (minimal):** force-push forbidden, deletion forbidden,
  direct push allowed, no required reviewers. CI runs on every push and tag
  but is not a merge blocker.

### Why not Git Flow

Git Flow assumes multiple contributors, parallel maintained versions,
scheduled release windows, and mandatory peer review. None hold for a
single-developer pre-alpha repo whose second contributor is an AI coding
assistant. The cost of `develop` / `release/*` / `hotfix/*` / forced PR
review exceeds the benefit at this stage.

### When to revisit

Adopt Git Flow (or GitHub Flow) once **any** of the following is true:

- A second permanent human contributor joins the repo.
- A production deployment exists and must be maintained separately from
  `main`'s in-progress work (a real reason for `develop`).
- Two or more versions must be supported in parallel (a real reason for
  `hotfix/*`).
