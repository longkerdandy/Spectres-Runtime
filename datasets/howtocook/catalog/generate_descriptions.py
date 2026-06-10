#!/usr/bin/env python3
"""Generate AI descriptions for HowToCook recipes via an LLM API.

Reads `recipes.jsonl`, calls the configured chat-completion endpoint to
produce a concise Chinese description for every recipe whose `description`
is null, then writes the enriched lines back to the same file.

Setup:
    Edit `generate_descriptions.json` with your API key:

    {
      "api_key": "sk-xxxxx",
      "base_url": "https://api.kimi.com/coding/v1",
      "model": "kimi-for-coding"
    }

    Then run:
    python generate_descriptions.py

    (This file is git-ignored; fill in your real key after checkout.)

Optional config fields (defaults shown):
    "max_completion_tokens": 120,
    "delay_seconds": 0.5

Supported providers:
  - Kimi Code:  https://api.kimi.com/coding/v1,  model="kimi-for-coding"
  - Moonshot:   https://api.moonshot.cn/v1,      model="kimi-k2.6"
  - Any OpenAI-compatible endpoint.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, cast

import httpx

CATALOG_DIR = Path(__file__).resolve().parent
RECIPE_FILE = CATALOG_DIR / "recipes.jsonl"
CONFIG_FILE = CATALOG_DIR / "generate_descriptions.json"

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
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": cfg.get("model", "default"),
        "messages": [{"role": "user", "content": prompt}],
        "max_completion_tokens": cfg.get("max_completion_tokens", 120),
    }

    resp = httpx.post(
        f"{cfg['base_url'].rstrip('/')}/chat/completions",
        headers=headers,
        json=payload,
        timeout=60.0,
    )
    resp.raise_for_status()

    data: dict[str, Any] = resp.json()
    choice: dict[str, Any] = data["choices"][0]
    message: dict[str, Any] = choice["message"]
    return str(message["content"]).strip()


def _build_prompt(recipe: dict[str, Any]) -> str:
    ingredients = "、".join(i["name"] for i in recipe.get("ingredients", []))
    return PROMPT_TEMPLATE.format(
        name=recipe["name"],
        ingredients=ingredients,
        difficulty=recipe.get("difficulty", "?"),
    )


def main() -> int:
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

    todo = [r for r in recipes if r.get("description") is None]
    if not todo:
        print("Nothing to do — every recipe already has a description.")
        return 0

    print(f"Generating descriptions for {len(todo)} recipes …")

    delay = cfg.get("delay_seconds", 0.5)
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

        if delay > 0:
            time.sleep(delay)

    print(f"\nWriting {len(recipes)} recipes back …")
    with RECIPE_FILE.open("w", encoding="utf-8") as f:
        for r in recipes:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"Done.  Success: {ok}  Errors: {errors}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
