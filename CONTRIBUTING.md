# Contributing to Spectres Runtime

This document collects the working conventions for anyone — human or AI
coding assistant — making changes to this repository. The architectural
overview lives in [`Agents.md`](./Agents.md); this file describes *how*
to work on the codebase, not *what* the codebase builds.

## Commit messages

This repository uses **[Conventional Commits 1.0](https://www.conventionalcommits.org/en/v1.0.0/)**.
Commit-message rules come in two tiers — be honest about which is which.

### Machine-enforced

Validated by the `commit-msg` git hook
(`compilerla/conventional-pre-commit`, installed via the pre-commit
framework). PR titles will additionally be validated by GitHub Actions
(planned, v0.1 §7). Violations are rejected.

- `type` must be one of: `feat`, `fix`, `docs`, `style`, `refactor`,
  `perf`, `test`, `build`, `ci`, `chore`, `revert`
- Shape must be `type(scope): subject` or `type: subject`
  (scope optional; `!` after type/scope marks a breaking change,
  e.g. `feat(api)!: drop legacy endpoint`)
- Subject must be non-empty
- Blank line required between subject and body when a body is present

### Project conventions

NOT machine-enforced — honour them anyway. They exist so the `git log`
stays readable and so reviewers do not spend energy on cosmetics.

- `subject`: imperative mood, lowercase, no trailing period, ≤ ~50 chars
  - ✓ `feat(agent): add agentfactory contract`
  - ✗ `Feat(Agent): Added new factory.`
- `scope`: lowercase module / area name. Suggested values:
  `agent`, `memory`, `knowledge`, `edge`, `auth`, `ci`, `deps`, `docs`
- `body`: wrap at ~72 chars; explain WHAT and WHY, not HOW; separate
  from the subject with a blank line
- `footer`: use `BREAKING CHANGE: <description>`, `Refs: #123`,
  `Closes: #123`

When in doubt, look at recent commits on `main` for the established
style.

## Setting up the hooks

After cloning the repository, install both git hooks once:

```bash
uv run pre-commit install                       # pre-commit stage
uv run pre-commit install --hook-type commit-msg
```

This is also covered in the README Quick start.
