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
    # appliances / vessels / disposable supplies seen across the catalog. The
    # bare single-character keys 杯 / 机 / 器 are intentional: no edible item in
    # the catalog contains them, but cookware/appliances frequently do.
    "杯",
    "机",
    "器",
    "秒表",
    "研杵",
    "吸管",
    "筛网",
    "量筒",
    "打火机",
    "过滤袋",
    "滤袋",
)

# Tokens that, if equal to the whole name, are tools even without a keyword.
TOOL_EXACT = {"油纸", "保鲜袋", "密封袋", "塑料袋", "案台"}

# Bare prep modifiers: dropped only when they are the WHOLE token (so they do
# not strip the same characters out of names like 带皮五花肉 / 去骨鸡腿).
MODIFIER_EXACT = {"带皮", "去皮", "去骨", "切块", "切片", "切丝", "切段", "洗净", "适量"}

# Water / ice spellings are consumable and always kept (some carry amounts that
# the quantity stripper reduces to these bare forms).
KEEP_WHITELIST |= {"凉白开", "矿泉水", "苏打水", "气泡水"}

# Section / category labels: as a stand-alone header line or as the `标签：…`
# prefix of a bullet, the label itself is dropped and any items after the colon
# are kept.
KNOWN_LABELS = {
    "原料",
    "用料",
    "食材",
    "材料",
    "主料",
    "辅料",
    "配料",
    "调料",
    "调味料",
    "主要原料",
    "其他原料",
    "其它原料",
    "工具",
    "其他",
    "其它",
}
OPTIONAL_LABELS = {"可选", "选用", "可选项"}

# Extra label words / suffixes used to tell `标签：条目列表` apart from
# `名称：数量`. A bullet whose pre-colon text is a label hands its real items to
# the post-colon part; anything else is treated as `name：amount`.
LABEL_WORDS = {"必备", "主食", "主要", "全部", "全料", "其他", "其它"}
LABEL_SUFFIX = ("料", "原料", "材料", "食材", "用料")

BULLET_RE = re.compile(r"^\s*[*\-+]\s+(.*\S)\s*$")
IMG_RE = re.compile(r"!\[[^\]]*\]\(\s*((?:[^()\s]|\([^()]*\))+)\s*\)")
SPLIT_RE = re.compile(r"[、，,/]")
OPTIONAL_RE = re.compile(r"（?\(?\s*(可选|选用)\s*）?\)?")
PAREN_RE = re.compile(r"（[^）]*）|\([^)]*\)")
STAR_RE = re.compile(r"★")

# `名称：数量` vs `标签：条目` — split on the first colon only.
COLON_RE = re.compile(r"[:：]")
# Sentence punctuation marks a bullet/token as prose (a note), not an item.
SENT_PUNCT_RE = re.compile(r"[。！？!?；;]")
# Instruction / note phrases that, when present, mean the token is prose.
PROSE_RE = re.compile(
    r"即可|可根据|根据个人|如果|尽量|最好|建议|注意|参见|参考|"
    r"前者|后者|价格|超市|市场|能够|没有就|否则|务必"
)
# Markdown image / link / emphasis fragments to strip from a name.
MD_IMG_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
BRACKET_RE = re.compile(r"[\[\]`*_]")
# Quantities: Arabic and Chinese numerals with an optional unit.
UNIT = (
    r"(?:g|kg|ml|l|克|千克|毫升|升|斤|两|个|只|颗|粒|片|张|块|根|条|瓣|朵|"
    r"勺|匙|大勺|小勺|大匙|小匙|杯|袋|包|盒|滴|把|束|份|寸|cm|mm|毫米|厘米|克左右)"
)
QTY_RE = re.compile(rf"\d+(?:[.\-~/]\d+)?\s*{UNIT}?", re.IGNORECASE)
CN_QTY_RE = re.compile(rf"[一二两三四五六七八九十几半数]+\s*{UNIT}")
# Stray amount / note words to strip (no digit, so QTY_RE misses them).
NOTE_RE = re.compile(r"适量|少许|若干|适当|品牌不限|不限|网孔[^ ]*|约[^ ，]*")


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


def clean_token(tok: str) -> str:
    """Reduce one split token to a bare ingredient name (no markdown/amounts)."""
    tok = MD_IMG_RE.sub("", tok)
    tok = MD_LINK_RE.sub(r"\1", tok)
    tok = BRACKET_RE.sub("", tok)
    tok = CN_QTY_RE.sub("", tok)
    tok = QTY_RE.sub("", tok)
    tok = NOTE_RE.sub("", tok)
    tok = re.sub(r"\s+", " ", tok)
    return tok.strip(" \t：:、，,./。·-—~+&")


def header_kind(line: str) -> str | None:
    """Classify a non-bullet line as a section header.

    Returns "tool" / "optional" / "plain" for a recognised header (which resets
    or sets the running section state), or None if the line is not a header.
    """
    core = PAREN_RE.sub("", line).strip().rstrip(":：").strip()
    is_header = line.rstrip().endswith((":", "：")) or core in KNOWN_LABELS or core in OPTIONAL_LABELS
    if not is_header:
        # bare "可选（…）" style sub-headers carry no colon
        if OPTIONAL_RE.search(line) and len(line.strip()) <= 12:
            return "optional"
        return None
    if "工具" in core:
        return "tool"
    if core in OPTIONAL_LABELS or OPTIONAL_RE.search(line):
        return "optional"
    return "plain"


def _is_label(s: str) -> bool:
    """True if `s` is a category label rather than an ingredient name."""
    if s in KNOWN_LABELS or s in OPTIONAL_LABELS or s in LABEL_WORDS:
        return True
    return s.endswith(LABEL_SUFFIX)


def split_label(text: str) -> tuple[str, bool, bool]:
    """Resolve a `标签：条目` / `名称：数量` / `名称：可选` bullet.

    Returns (working_text, optional_from_label, drop_bullet).
    """
    m = COLON_RE.search(text)
    if not m:
        return text, False, False
    before = text[: m.start()].strip()
    after = text[m.end() :].strip()
    drop_tool = "工具" in before
    if not before:
        # leading colon (label sat inside a stripped `（可选）`/parenthetical)
        return after, False, drop_tool
    if before in KNOWN_LABELS:
        return after, False, drop_tool
    if before in OPTIONAL_LABELS:
        return after, True, drop_tool
    if not after:
        # `名称：`-style category header with nothing after → drop
        return "", False, True
    if not OPTIONAL_RE.sub("", after).strip():
        # `名称：可选` — the optional marker is the whole after-part
        return before, True, drop_tool
    if _is_label(before):
        # `全香料：月桂叶、…`, `必备：蒜蓉酱` → real item(s) follow the colon
        return after, bool(OPTIONAL_RE.search(before)), drop_tool
    # `名称：数量/备注/说明` → the ingredient is the part before the colon
    return before, False, drop_tool


def extract_ingredients(region: list[str]) -> list[dict]:
    # find the `## 必备原料和工具` section within the region
    start = None
    for i, ln in enumerate(region):
        if ln.strip().startswith("##") and "必备原料和工具" in ln:
            start = i + 1
            break
    if start is None:
        return []

    out: list[dict] = []
    seen: set[str] = set()
    section_optional = False
    section_drop = False  # under a `工具：` header

    for ln in region[start:]:
        if ln.strip().startswith("## "):
            break
        m = BULLET_RE.match(ln)
        if not m:
            if not ln.strip():
                continue
            kind = header_kind(ln)
            if kind == "tool":
                section_drop, section_optional = True, False
            elif kind == "optional":
                section_drop, section_optional = False, True
            elif kind == "plain":
                section_drop, section_optional = False, False
            continue

        if section_drop:
            continue
        raw = m.group(1)
        # strip markdown images/links first so their `!`/`[]` don't read as prose
        raw = MD_IMG_RE.sub("", raw)
        raw = MD_LINK_RE.sub(r"\1", raw)
        inline_optional = bool(OPTIONAL_RE.search(raw))
        cleaned = PAREN_RE.sub("", raw)
        if SENT_PUNCT_RE.search(cleaned) or cleaned.strip().startswith("注"):
            continue  # prose note, not an ingredient
        work, label_optional, drop = split_label(cleaned)
        if drop:
            continue
        work = OPTIONAL_RE.sub("", work)  # drop any bare 可选/选用 left among items
        optional = section_optional or inline_optional or label_optional
        for piece in SPLIT_RE.split(work):
            name = clean_token(piece)
            if not name or name in KNOWN_LABELS or name in OPTIONAL_LABELS:
                continue
            if name in MODIFIER_EXACT:
                continue
            if PROSE_RE.search(name) or SENT_PUNCT_RE.search(name):
                continue
            if not re.search(r"[\u4e00-\u9fffA-Za-z]", name):
                continue  # nothing but leftover digits/punctuation
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
