# HowToCook — vendored snapshot

This directory is a **pinned, offline snapshot** of the recipe Markdown from the
upstream [`Anduin2017/HowToCook`](https://github.com/Anduin2017/HowToCook)
project — the Phase A ingestion source (plan
[`v0.3-recipe-ingestion.md`](../../docs/plans/v0.3-recipe-ingestion.md) §5, design
`docs/design/recipe-agent.md` §2.2). It is vendored so ingestion reads from a
**local snapshot with zero network**, and so the corpus is **reproducible**: a
re-fetch is an explicit, reviewed bump, never an implicit moving target.

## Pin

| Field | Value |
|---|---|
| Source | https://github.com/Anduin2017/HowToCook |
| Release tag | `1.6.0` |
| Commit | `a0b14bd388ee996943173679c3a7c9db7da04a6c` |
| Fetched | 2026-06-04 |
| Archive | `https://github.com/Anduin2017/HowToCook/archive/refs/tags/1.6.0.tar.gz` |

## What is vendored

- **Only the recipe Markdown** under `dishes/` — 358 `.md` files across the
  upstream categories (`vegetable_dish/`, `meat_dish/`, `aquatic/`, `soup/`,
  `staple/`, `breakfast/`, `dessert/`, `drink/`, `condiment/`, `semi-finished/`,
  and the `template/` example).
- The directory layout mirrors upstream exactly: most dishes are
  `dishes/<category>/<name>.md`; dishes that ship with photos use a per-dish
  folder `dishes/<category>/<name>/<name>.md`.

## What is **not** vendored

- **Images** (`.jpg/.jpeg/.png/.webp`, ~330 files upstream). v0.3 records image
  references as runtime-resolvable strings only; it does not copy or serve media
  (plan §6, §"Out of Scope"). The `Recipe.images` refs therefore point at upstream
  paths that are intentionally absent from this snapshot.
- Build tooling, site/docs, `tips/`, and everything outside `dishes/`.

## License

Upstream is released under **The Unlicense** (public-domain dedication); the full
text is in [`UNLICENSE`](./UNLICENSE). The author additionally, in the upstream
`CODE_OF_CONDUCT.md` ("弱协议"), explicitly invites commercial and non-commercial
reuse. This subtree is therefore public domain and is included here unmodified;
it is **not** governed by this repository's top-level Apache-2.0 license.

## Updating the snapshot

1. Bump the tag/commit above and re-fetch the archive.
2. Re-extract **only** `dishes/**/*.md` into `dishes/` (overwriting).
3. Re-run ingestion — the sink re-embeds only changed recipes (content-hash
   idempotency, plan §7); unchanged recipes are skipped.
