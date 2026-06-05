#!/usr/bin/env python3
"""HowToCook dish .md -> recipes.jsonl cleaner.

Implements datasets/howtocook/ai-cleaned/INSTRUCTIONS.md as a deterministic
heuristic pass:

  - read only the region H1 .. (not including) `## 计算`
  - name   = filename stem of ref
  - description = first prose paragraph between H1 and 预估烹饪难度 / any `##`
  - images = ![..](TARGET) in the H1..first-`##` block, resolved relative to
             the dishes/ root, leading `./` stripped, http(s) ignored
  - difficulty = count of ★ on the 预估烹饪难度 line (1-5) else null
  - ingredients = `## 必备原料和工具` bullets, tools dropped, multi-item bullets
                  split on 、，,/ (NOT 或), parenthetical notes stripped,
                  optional flagged on 可选/选用 markers, deduped in order

Output: one compact single-line JSON object per dish, sorted by ref.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DISHES = ROOT / "datasets" / "howtocook" / "dishes"
OUT = ROOT / "datasets" / "howtocook" / "ai-cleaned" / "recipes.jsonl"

# ---------------------------------------------------------------------------
# Tool / equipment detection (the one semantic call, done heuristically).
# Keep only edible items; drop cookware, appliances, and consumable supplies.
# Water and ice are edible/consumable and are explicitly kept.
# ---------------------------------------------------------------------------
KEEP_WHITELIST = {
    "水",
    "清水",
    "开水",
    "热水",
    "冷水",
    "温水",
    "凉水",
    "冰水",
    "纯净水",
    "矿泉水",
    "饮用水",
    "冰",
    "冰块",
}

# Substrings that mark a bullet as a tool/appliance/supply (not an ingredient).
TOOL_KEYWORDS = (
    "锅",
    "刀",
    "铲",
    "勺",
    "碗",
    "盆",
    "盘",
    "碟",
    "筷",
    "叉子",
    "夹",
    "烤箱",
    "微波炉",
    "电饭煲",
    "电饭锅",
    "电饼铛",
    "面包机",
    "空气炸",
    "料理机",
    "搅拌机",
    "破壁机",
    "粉碎机",
    "绞肉机",
    "豆浆机",
    "榨汁",
    "打蛋器",
    "擀面杖",
    "擀面棍",
    "砧板",
    "案板",
    "菜板",
    "面板",
    "牙签",
    "竹签",
    "签子",
    "厨房纸",
    "吸油纸",
    "厨房用纸",
    "纸巾",
    "保鲜膜",
    "锡纸",
    "铝箔",
    "油纸",
    "烘焙纸",
    "手套",
    "温度计",
    "模具",
    "模子",
    "裱花",
    "蒸笼",
    "蒸架",
    "蒸篦",
    "蒸格",
    "篦子",
    "漏勺",
    "滤网",
    "笊篱",
    "簸箕",
    "炉",
    "灶",
    "高压锅",
    "压力锅",
    "蒜臼",
    "研磨",
    "喷壶",
    "喷瓶",
    "计时",
    "电子秤",
    "厨房秤",
    "称",
    "容器",
    "保鲜盒",
    "饭盒",
    "烤盘",
    "烤架",
    "烤网",
    "晾网",
    "网架",
    "棉线",
    "棉绳",
    "纱布",
    "滤纸",
    "镊子",
    "刷子",
    "毛刷",
    "刮刀",
    "刨",
    "擦",
    "压泥器",
    "捣",
    "搅拌棒",
    "硅胶",
    "工具",
    "器具",
    "瓶子",
    "罐子",
    "杯子",
    "量杯",
    "量勺",
    "汤匙",
    "瓢",
    "盅",
)

# Tokens that, if equal to the whole name, are tools even without a keyword.
TOOL_EXACT = {"油纸", "保鲜袋", "密封袋", "塑料袋", "案台"}

BULLET_RE = re.compile(r"^\s*[*\-+]\s+(.*\S)\s*$")
IMG_RE = re.compile(r"!\[[^\]]*\]\(\s*((?:[^()\s]|\([^()]*\))+)\s*\)")
SPLIT_RE = re.compile(r"[、，,/]")
OPTIONAL_RE = re.compile(r"（?\(?\s*(可选|选用)\s*）?\)?")
PAREN_RE = re.compile(r"（[^）]*）|\([^)]*\)")
STAR_RE = re.compile(r"★")


def normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def read_region(lines: list[str]) -> list[str]:
    """Lines from H1 down to (not including) `## 计算`."""
    start = 0
    for i, ln in enumerate(lines):
        if ln.startswith("# ") and not ln.startswith("## "):
            start = i
            break
    region = []
    for ln in lines[start:]:
        if ln.strip().startswith("## 计算"):
            break
        region.append(ln)
    return region


def first_h2_index(region: list[str]) -> int:
    for i, ln in enumerate(region):
        if ln.strip().startswith("## "):
            return i
    return len(region)


def extract_description(region: list[str]) -> str | None:
    # search between H1 (index 0) and first `##` / 预估烹饪难度 line
    end = first_h2_index(region)
    para: list[str] = []
    for ln in region[1:end]:
        s = ln.strip()
        if s.startswith("预估烹饪难度"):
            break
        if not s:
            if para:
                break
            continue
        if s.startswith("!["):  # image line
            if para:
                break
            continue
        if s.startswith(">"):  # blockquote subtitle, not prose
            if para:
                break
            continue
        if s.startswith("#"):
            break
        para.append(s)
    return "\n".join(para) if para else None


def extract_images(region: list[str], ref: str) -> list[str]:
    end = first_h2_index(region)
    base = str(Path(ref).parent)
    out: list[str] = []
    for ln in region[:end]:
        for target in IMG_RE.findall(ln):
            if target.startswith(("http://", "https://")):
                continue
            t = target
            if t.startswith("./"):
                t = t[2:]
            resolved = str(Path(base) / t) if base and base != "." else t
            resolved = resolved.replace("\\", "/")
            if resolved not in out:
                out.append(resolved)
    return out


def extract_difficulty(region: list[str]) -> int | None:
    for ln in region:
        if "预估烹饪难度" in ln:
            n = len(STAR_RE.findall(ln))
            return n if 1 <= n <= 5 else None
    return None


def is_tool(name: str) -> bool:
    if name in KEEP_WHITELIST:
        return False
    if name in TOOL_EXACT:
        return True
    return any(k in name for k in TOOL_KEYWORDS)


def extract_ingredients(region: list[str]) -> list[dict]:
    # find the `## 必备原料和工具` section within the region
    start = None
    for i, ln in enumerate(region):
        if ln.strip().startswith("##") and "必备原料和工具" in ln:
            start = i + 1
            break
    if start is None:
        return []
    bullets: list[str] = []
    for ln in region[start:]:
        if ln.strip().startswith("## "):
            break
        m = BULLET_RE.match(ln)
        if m:
            bullets.append(m.group(1))

    out: list[dict] = []
    seen: set[str] = set()
    for raw in bullets:
        optional = bool(OPTIONAL_RE.search(raw))
        # strip parenthetical notes (and the optional markers within them)
        cleaned = PAREN_RE.sub("", raw)
        cleaned = OPTIONAL_RE.sub("", cleaned)
        for piece in SPLIT_RE.split(cleaned):
            name = piece.strip().strip("：:").strip()
            # drop trailing/leading markdown emphasis
            name = name.strip("*_` ").strip()
            if not name:
                continue
            if "：" in name or ":" in name:  # sub-header label remnants
                name = re.split(r"[：:]", name)[-1].strip()
            if not name:
                continue
            if is_tool(name):
                continue
            if name in seen:
                continue
            seen.add(name)
            out.append({"name": name, "optional": optional})
    return out


def process(path: Path) -> dict:
    ref = str(path.relative_to(DISHES)).replace("\\", "/")
    text = normalize(path.read_text(encoding="utf-8"))
    lines = text.split("\n")
    region = read_region(lines)
    return {
        "ref": ref,
        "name": path.stem,
        "description": extract_description(region),
        "images": extract_images(region, ref),
        "difficulty": extract_difficulty(region),
        "ingredients": extract_ingredients(region),
    }


def main() -> None:
    files = sorted(p for p in DISHES.rglob("*.md") if "template" not in p.relative_to(DISHES).parts)
    records = [process(p) for p in files]
    records.sort(key=lambda r: r["ref"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")))
            fh.write("\n")
    print(f"wrote {len(records)} records -> {OUT}")


if __name__ == "__main__":
    main()
