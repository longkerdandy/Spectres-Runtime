#!/usr/bin/env python3
"""Generate AI descriptions for HowToCook recipes using Kimi API.

Usage:
    # 1. Copy the template config and fill in your API key:
    cp generate_descriptions.json generate_descriptions.local.json
    # Edit generate_descriptions.local.json and set api_key

    # 2. Run the script:
    python generate_descriptions.py

    # 3. Review changes and commit recipes.jsonl

The script reads generate_descriptions.local.json (git-ignored) for Kimi API
parameters. It processes recipes.jsonl line-by-line, calls the Kimi chat
completion API to generate concise descriptions, and writes results back.

Features:
- Resume support: saves progress to .progress.json
- Rate limiting: configurable delay between batches
- Idempotent: skips already-processed recipes on re-run
- Only-null mode: by default only fills missing descriptions
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

CATALOG_DIR = Path(__file__).resolve().parent
RECIPE_FILE = CATALOG_DIR / "recipes.jsonl"
CONFIG_FILE = CATALOG_DIR / "generate_descriptions.local.json"
PROGRESS_FILE = CATALOG_DIR / ".progress.json"

DEFAULT_PROMPT_TEMPLATE = """\
为以下菜谱生成一段 50-80 字的中文描述，要求：
- 突出主要食材和口味特点
- 提及制作难度或耗时
- 语言简洁，不要废话
- 不要包含做法步骤

菜名：{name}
食材：{ingredients}
难度：{difficulty}/5

描述："""


def load_config() -> dict[str, Any]:
    """Load API config from local JSON file."""
    if not CONFIG_FILE.exists():
        print(f"Error: Config file not found: {CONFIG_FILE}")
        print("Please copy generate_descriptions.json to generate_descriptions.local.json")
        print("and fill in your Kimi API key.")
        sys.exit(1)

    with CONFIG_FILE.open(encoding="utf-8") as f:
        return json.load(f)


def load_progress() -> set[str]:
    """Load set of already-processed recipe refs from progress file."""
    if not PROGRESS_FILE.exists():
        return set()
    with PROGRESS_FILE.open(encoding="utf-8") as f:
        data = json.load(f)
        return set(data.get("completed", []))


def save_progress(completed: set[str]) -> None:
    """Save progress to file."""
    with PROGRESS_FILE.open("w", encoding="utf-8") as f:
        json.dump({"completed": sorted(completed)}, f, ensure_ascii=False, indent=2)


def call_kimi_api(prompt: str, config: dict[str, Any]) -> str:
    """Call Kimi chat completion API and return generated text."""
    api_key = config["api_key"]
    base_url = config.get("base_url", "https://api.moonshot.cn/v1")
    model = config.get("model", "kimi-latest")
    temperature = config.get("temperature", 0.3)
    max_tokens = config.get("max_tokens", 120)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    response = httpx.post(
        f"{base_url}/chat/completions",
        headers=headers,
        json=payload,
        timeout=60.0,
    )
    response.raise_for_status()
    data = response.json()

    return data["choices"][0]["message"]["content"].strip()


def should_process(recipe: dict[str, Any], config: dict[str, Any]) -> bool:
    """Determine if this recipe needs description generation."""
    force = config.get("force_regenerate", False)
    only_null = config.get("only_null", True)

    if force:
        return True

    current_desc = recipe.get("description")
    if current_desc is None:
        return True

    if only_null:
        return False

    # Additional heuristics for low-quality descriptions
    if isinstance(current_desc, str):
        # Skip HTML comments
        if current_desc.startswith("<"):
            return True
        # Skip WARNING prefixes
        if "WARNING" in current_desc or "WARNING" in current_desc:
            return True
        # Skip very short (< 20 chars)
        if len(current_desc) < 20:
            return True
        # Skip very long (> 200 chars)
        if len(current_desc) > 200:
            return True

    return False


def build_prompt(recipe: dict[str, Any]) -> str:
    """Construct prompt from recipe data."""
    ingredients_str = "、".join(i["name"] for i in recipe.get("ingredients", []))
    return DEFAULT_PROMPT_TEMPLATE.format(
        name=recipe["name"],
        ingredients=ingredients_str,
        difficulty=recipe.get("difficulty", "?"),
    )


def main() -> int:
    config = load_config()
    completed = load_progress()

    # Validate API key
    if not config.get("api_key") or config["api_key"].startswith("your-"):
        print("Error: API key not configured in generate_descriptions.local.json")
        sys.exit(1)

    # Read all recipes
    recipes: list[dict[str, Any]] = []
    with RECIPE_FILE.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                recipes.append(json.loads(line))

    total = len(recipes)
    to_process = []
    for recipe in recipes:
        ref = recipe["ref"]
        if ref not in completed and should_process(recipe, config):
            to_process.append(recipe)

    print(f"Total recipes: {total}")
    print(f"Already completed: {len(completed)}")
    print(f"To process: {len(to_process)}")

    if not to_process:
        print("Nothing to do. All recipes have descriptions.")
        return 0

    batch_size = config.get("batch_size", 5)
    delay = config.get("delay_seconds", 1.0)

    updated_count = 0
    error_count = 0

    for idx, recipe in enumerate(to_process, 1):
        ref = recipe["ref"]
        name = recipe["name"]

        print(f"[{idx}/{len(to_process)}] Processing: {name} ...", end=" ")

        try:
            prompt = build_prompt(recipe)
            description = call_kimi_api(prompt, config)

            # Clean up description
            description = description.strip().strip('"').strip("'").strip()

            recipe["description"] = description
            completed.add(ref)
            updated_count += 1
            print(f"OK ({len(description)} chars)")

        except Exception as e:
            error_count += 1
            print(f"ERROR: {e}")
            # Don't add to completed so it will be retried

        # Save progress every batch
        if idx % batch_size == 0:
            save_progress(completed)
            print(f"  Progress saved: {len(completed)}/{total}")
            if delay > 0:
                time.sleep(delay)

    # Final save
    save_progress(completed)

    # Write back recipes.jsonl
    print(f"\nWriting {total} recipes back to {RECIPE_FILE.name} ...")
    with RECIPE_FILE.open("w", encoding="utf-8") as f:
        for recipe in recipes:
            f.write(json.dumps(recipe, ensure_ascii=False) + "\n")

    print("\nDone!")
    print(f"  Updated: {updated_count}")
    print(f"  Errors: {error_count}")
    print(f"  Total completed: {len(completed)}/{total}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
