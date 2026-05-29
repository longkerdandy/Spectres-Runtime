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
