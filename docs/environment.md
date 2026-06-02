# Development Environment

Setup, daily commands, and troubleshooting for working on Spectres-Runtime
locally. For commit / branching conventions see
[`CONTRIBUTING.md`](../CONTRIBUTING.md).

## Prerequisites

- Linux, macOS, or WSL2 (native Windows untested).
- Git ≥ 2.30.
- [`uv`](https://docs.astral.sh/uv/) ≥ 0.11.17 — manages Python, deps, and venv.
- No system Python required; `uv` fetches its own.

Python is pinned to **3.12** (`requires-python = ">=3.12,<3.13"`) — upper bound
locked until 3.13 wheel coverage matures for native deps.

## Install `uv`

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # or: brew install uv
uv --version          # expect ≥ 0.11.17
uv self update        # upgrade later
```

## First-time setup

```bash
git clone https://github.com/longkerdandy/Spectres-Runtime.git
cd Spectres-Runtime
uv python install 3.12                             # fetch pinned interpreter
uv sync                                            # runtime + dev (lint + test + mypy + pre-commit)
uv run pre-commit install                          # pre-commit stage
uv run pre-commit install --hook-type commit-msg   # commit-msg stage (separate, required)
```

Use `uv sync --frozen` in CI/scripts to forbid silent lockfile regeneration.

## Smoke verification

```bash
uv run ruff check .            # lint
uv run ruff format --check .   # formatter dry-run
uv run mypy                    # strict type check
uv run pytest                  # tests + coverage gate (≥ 80%)

uv run uvicorn spectres_runtime.app:app --reload
curl -s http://127.0.0.1:8000/health   # → {"status":"ok",...}
```

OpenAPI: `/openapi.json`; Swagger UI: `/docs`.

## Daily commands

| Task | Command |
|---|---|
| Lint (with auto-fix) | `uv run ruff check --fix .` |
| Format | `uv run ruff format .` |
| Type check | `uv run mypy` |
| Run tests | `uv run pytest` |
| Run a single test | `uv run pytest tests/test_health.py::test_health_returns_ok` |
| Coverage HTML | `uv run pytest --cov-report=html` → `htmlcov/index.html` |
| Run all hooks | `uv run pre-commit run --all-files` |
| Update hook versions | `uv run pre-commit autoupdate` |
| Bypass hooks (rare) | `git commit --no-verify` |
| Add dependency | `uv add <pkg>` (or `--group dev` / `lint` / `test`) |
| Remove dependency | `uv remove <pkg>` |
| Upgrade one / all | `uv lock --upgrade-package <pkg>` / `uv lock --upgrade` |
| Dependency tree | `uv tree` |
| Dev server | `uv run uvicorn spectres_runtime.app:app --reload` |

Every dependency change must commit the updated `uv.lock`.

## Pre-commit ↔ CI

Both run the same checks; intentionally redundant. Pre-commit uses isolated
per-hook venvs and runs on staged files (fast feedback); CI uses the project
`.venv` on the full tree and is the authoritative gate.

The Mypy hook lives in its own venv and cannot see `.venv`, so third-party
packages it needs are listed under `additional_dependencies` in
`.pre-commit-config.yaml`. **When you bump a runtime dep, mirror the bump
there.**

## GPU / local inference (dev-only)

Recipe ingestion (v0.3+) embeds with **Qwen3-Embedding-8B** (4096-dim) on a local
GPU. This is a **dev-box convenience for the offline ingest batch only** — the
Runtime service needs no GPU, and **CI never uses one** (it uses a small CPU
embedder or skips the integration tier). Skip this whole section unless you are
running ingestion locally.

Reference dev box: **RTX 5090 (Blackwell, `sm_120`)** under **WSL2**.

- **Driver lives on the Windows host, never inside WSL.** WSL2 reaches the GPU
  through the host driver via `/usr/lib/wsl/lib/libcuda.so`. Keep the Windows
  NVIDIA driver current; do **not** `apt install` an NVIDIA driver inside WSL.
  WSL1 has no GPU passthrough.
- **Blackwell requires a CUDA 12.8 (`cu128`) PyTorch build.** Older `torch`
  wheels ship no `sm_120` kernels and fail with *"no kernel image is available"*
  or silently fall back to CPU. `torch.cuda.is_available() == True` is **not**
  sufficient proof — a real CUDA kernel must run.
- **Keep the HF cache on the native filesystem.** Point `HF_HOME` at a WSL-native
  path (e.g. `~/.cache/huggingface`), **never** under `/mnt/c/...` — cross-
  filesystem I/O makes loading the multi-GB weights painfully slow.

### Verification gate

Confirms passthrough + a `sm_120`-capable torch that actually executes a kernel.
The ephemeral `--with` invocation pulls a cu128 `torch` without touching the
project env (the pinned project dependency lands in v0.3 §3):

```bash
nvidia-smi   # RTX 5090 listed; note "CUDA UMD Version"

uv run --no-project --with torch \
  --index https://download.pytorch.org/whl/cu128 python - <<'PY'
import torch
assert torch.cuda.is_available(), "CUDA not available"
cap = torch.cuda.get_device_capability()
assert cap[0] >= 12, f"not Blackwell-capable torch, got sm_{cap[0]}{cap[1]}"
print(torch.__version__, "/ cuda", torch.version.cuda)
print(torch.cuda.get_device_name(0), cap)
x = torch.randn(1024, 1024, device="cuda")
y = torch.randn(1024, 1024, device="cuda")
print("matmul ok:", (x @ y).sum().item())   # real sm_120 kernel, not CPU fallback
PY
```

Expected (verified 2026-06): `torch 2.11.0+cu128 / cuda 12.8`,
`NVIDIA GeForce RTX 5090 (12, 0)`, and a finite `matmul ok` value. A
`Failed to initialize NumPy` warning from the ephemeral env is harmless (no
`numpy` installed there; the real project pulls it in transitively).

## Troubleshooting

- **`uv sync` says lockfile is out of date** — `pyproject.toml` changed without
  relocking. Run `uv lock`, review the diff, commit.
- **Pre-commit Ruff result differs from `uv run ruff`** — version drift between
  `.pre-commit-config.yaml` `rev:` and the `ruff>=` lower bound in
  `pyproject.toml`. Bump both together.
- **Pre-commit Mypy: "module not found"** — add it to `additional_dependencies`
  under the `mypy` hook.
- **`uvicorn: command not found`** — always prefix with `uv run`.
- **`commit-msg` hook does not fire** — install the second stage:
  `uv run pre-commit install --hook-type commit-msg`.
- **`nvidia-smi` not found / GPU missing inside WSL** — update the NVIDIA driver
  on the *Windows* host (do not install one in WSL), then `wsl --shutdown` from
  Windows and reopen. Confirm `/usr/lib/wsl/lib/libcuda.so` exists.
- **torch: "no kernel image is available for execution"** — a non-`cu128` wheel
  on Blackwell. Reinstall from the cu128 index (see GPU verification gate).
- **`git push` rejected by push protection** — GitHub detected a secret
  in the pushed commits. Do not bypass blindly. Either rewrite history to
  remove the secret (`git rebase -i` + force-push is blocked on `main`;
  reset the offending commit before pushing) or, if the match is a known
  false positive, follow the unblock URL in the error message to allow it
  with a recorded reason. Rotate any real secret that has already left
  your machine, even if the push was blocked.

## Reset

```bash
rm -rf .venv .mypy_cache .ruff_cache .pytest_cache htmlcov
uv sync --frozen
uv run pre-commit install && uv run pre-commit install --hook-type commit-msg
uv run pytest
```
