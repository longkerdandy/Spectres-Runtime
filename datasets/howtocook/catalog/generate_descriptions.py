#!/usr/bin/env python3
"""Generate AI descriptions for HowToCook recipes via an LLM API.

Reads `recipes.jsonl`, calls the configured chat-completion endpoint to
produce a concise Chinese description for every recipe whose `description`
is null or empty, then writes the enriched lines back to the same file.

Setup:
    Edit `generate_descriptions.json` with your API key:

    {
      "api_key": "sk-xxxxx",
      "base_url": "https://api.kimi.com/coding/v1",
      "model": "kimi-for-coding",
      "max_completion_tokens": 500
    }

    Then run:
    python generate_descriptions.py

    (This file is git-ignored; fill in your real key after checkout.)

Optional config fields (defaults shown):
    "max_completion_tokens": 120,
    "delay_seconds": 0.0,
    "batch_size": 10
    "timeout_seconds": 60.0

User-Agent:
    When running inside OpenCode the script auto-detects the local version
    (via `opencode --version` or the plugin package.json) and sends it as the
    User-Agent header. You can override it with the optional `user_agent` field.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast

import httpx

CATALOG_DIR = Path(__file__).resolve().parent
RECIPE_FILE = CATALOG_DIR / "recipes.jsonl"
CONFIG_FILE = CATALOG_DIR / "generate_descriptions.json"

# Auto-detect OpenCode version for User-Agent when running inside OpenCode.
_OPCODEC_EXE = Path.home() / ".opencode" / "bin" / "opencode"
_OPCODEC_PKG = Path.home() / ".config" / "opencode" / "node_modules" / "@opencode-ai" / "plugin" / "package.json"


def _detect_opencode_version() -> str | None:
    """Try to discover the local OpenCode version."""
    for exe in (_OPCODEC_EXE, "opencode"):
        try:
            result = subprocess.run(
                [str(exe), "--version"],
                capture_output=True,
                text=True,
                timeout=5.0,
                check=False,
            )
            if result.returncode == 0:
                ver = result.stdout.strip().split()[0]
                if ver:
                    return f"opencode/{ver}"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    if _OPCODEC_PKG.exists():
        try:
            data = json.loads(_OPCODEC_PKG.read_text(encoding="utf-8"))
            ver = data.get("version", "").strip()
            if ver:
                return f"opencode/{ver}"
        except (json.JSONDecodeError, OSError):
            pass

    return None


PROMPT_TEMPLATE = """\
为以下菜谱生成一段 50-80 字的中文描述，要求：
- 突出主要食材和口味特点
- 提及制作难度或耗时
- 语言简洁，不要废话
- 不要包含做法步骤

菜名：{name}
食材：{ingredients}
难度：{difficulty}/5

描述："""


def _load_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        print(f"Config not found: {CONFIG_FILE}")
        sys.exit(1)
    with CONFIG_FILE.open(encoding="utf-8") as f:
        return cast(dict[str, Any], json.load(f))


def _call_llm(prompt: str, cfg: dict[str, Any]) -> str:
    """Call the configured chat-completion endpoint."""
    user_agent = cfg.get("user_agent") or _detect_opencode_version() or "opencode"
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
        "User-Agent": user_agent,
    }
    payload: dict[str, Any] = {
        "model": cfg.get("model", "default"),
        "messages": [{"role": "user", "content": prompt}],
        "max_completion_tokens": cfg.get("max_completion_tokens", 120),
    }

    # Disable reasoning/thinking if configured
    if cfg.get("disable_reasoning", False):
        payload["thinking"] = {"type": "disabled"}

    timeout = cfg.get("timeout_seconds", 60.0)
    resp = httpx.post(
        f"{cfg['base_url'].rstrip('/')}/chat/completions",
        headers=headers,
        json=payload,
        timeout=timeout,
    )
    resp.raise_for_status()

    data: dict[str, Any] = resp.json()
    choice: dict[str, Any] = data["choices"][0]
    message: dict[str, Any] = choice["message"]
    content = str(message.get("content", "")).strip()

    # Some models return reasoning_content but empty content
    if not content and "reasoning_content" in message:
        reasoning = str(message["reasoning_content"]).strip()
        # Try to extract the final description from reasoning
        lines = [line.strip() for line in reasoning.split("\n") if line.strip()]
        if lines:
            content = lines[-1]  # Usually the last line is the answer

    return content


def _build_prompt(recipe: dict[str, Any]) -> str:
    ingredients = "、".join(i["name"] for i in recipe.get("ingredients", []))
    return PROMPT_TEMPLATE.format(
        name=recipe["name"],
        ingredients=ingredients,
        difficulty=recipe.get("difficulty", "?"),
    )


def _save_recipes(recipes: list[dict[str, Any]]) -> None:
    """Atomically write recipes back to file."""
    tmp_file = RECIPE_FILE.with_suffix(".tmp")
    with tmp_file.open("w", encoding="utf-8") as f:
        for r in recipes:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp_file.replace(RECIPE_FILE)


def main(overwrite: bool = False) -> int:
    cfg = _load_config()

    if not cfg.get("api_key") or str(cfg["api_key"]).startswith("your-"):
        print("API key not set in config.")
        return 1

    recipes: list[dict[str, Any]] = []
    with RECIPE_FILE.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                recipes.append(json.loads(line))

    if overwrite:
        todo = recipes[:]
        print(f"Overwrite mode — regenerating all {len(todo)} descriptions …")
    else:
        todo = [r for r in recipes if not r.get("description")]
        if not todo:
            print("Nothing to do — every recipe already has a description.")
            return 0
        print(f"Generating descriptions for {len(todo)} recipes …")

    delay = cfg.get("delay_seconds", 0.0)
    batch_size = cfg.get("batch_size", 10)
    ok = errors = 0

    for idx, recipe in enumerate(todo, 1):
        try:
            desc = _call_llm(_build_prompt(recipe), cfg)
            recipe["description"] = desc.strip('"').strip("'")
            ok += 1
            print(f"  [{idx}/{len(todo)}] {recipe['name']} — {len(desc)} chars")
        except Exception as exc:
            errors += 1
            print(f"  [{idx}/{len(todo)}] {recipe['name']} — ERROR: {exc}")

        # Save progress every batch
        if idx % batch_size == 0:
            print(f"    [checkpoint] Saving progress ({idx}/{len(todo)}) …")
            _save_recipes(recipes)

        if delay > 0:
            time.sleep(delay)

    # Final save
    print(f"\nWriting {len(recipes)} recipes back …")
    _save_recipes(recipes)

    print(f"Done.  Success: {ok}  Errors: {errors}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate AI descriptions for HowToCook recipes.")
    parser.add_argument(
        "--overwrite",
        "-o",
        action="store_true",
        help="Regenerate descriptions even for recipes that already have one.",
    )
    args = parser.parse_args()
    sys.exit(main(overwrite=args.overwrite))
