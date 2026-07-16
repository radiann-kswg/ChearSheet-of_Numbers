"""assets/numbers-index.json（Numbers Lore Viewer 用の検索インデックス）を生成する。

ビューアー（index.html / assets/app.js）は本 JSON の filters をチップ UI として描画し、
records の loreFilters / propertyFilters / searchText で絞り込みを行う。
`generate_numbers.py` の実行後（または単体で）呼び出して、ページ内容と同期させる。

使い方:
    python tools/build_viewer_index.py
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import generate_numbers as gen

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "assets" / "numbers-index.json"

# ビューアーのチップ表示順（いわれカテゴリ）
LORE_FILTER_DEFS = [
    {"key": "numerology", "label": "数秘・エンジェル"},
    {"key": "gematria", "label": "ゲマトリア"},
    {"key": "kikkyo", "label": "吉凶・忌み数"},
    {"key": "folklore", "label": "伝承・神話・名数"},
    {"key": "meisu", "label": "番号のいわれ"},
    {"key": "goro", "label": "語呂合わせ・スラング"},
    {"key": "fiction", "label": "創作作品"},
]

# ビューアーのチップ表示順（性質カテゴリ）。
# 先頭は分類・偶奇、続いて古典フラグ、その後に拡張フラグ（フラグの解説と対応）。
PROPERTY_FILTER_DEFS = [
    {"key": "special", "label": "特殊（0/1）"},
    {"key": "prime", "label": "素数"},
    {"key": "composite", "label": "合成数"},
    {"key": "even", "label": "偶数"},
    {"key": "odd", "label": "奇数"},
    {"key": "square", "label": "平方数"},
    {"key": "cube", "label": "立方数"},
    {"key": "triangular", "label": "三角数"},
    {"key": "fibonacci", "label": "フィボナッチ数"},
    {"key": "mersenne", "label": "メルセンヌ数"},
    {"key": "perfect", "label": "完全数"},
    {"key": "abundant", "label": "過剰数"},
    {"key": "deficient", "label": "不足数"},
    {"key": "semiprime", "label": "半素数"},
    {"key": "sphenic", "label": "楔数"},
    {"key": "harshad", "label": "ハーシャッド数"},
    {"key": "happy", "label": "ハッピー数"},
    {"key": "palindrome", "label": "回文数"},
    {"key": "palindromic_prime", "label": "回文素数"},
    {"key": "emirp", "label": "エマープ"},
    {"key": "twin_prime", "label": "双子素数"},
    {"key": "sophie_germain", "label": "ソフィー・ジェルマン素数"},
    {"key": "safe_prime", "label": "安全素数"},
    {"key": "highly_composite", "label": "高度合成数"},
    {"key": "factorial", "label": "階乗数"},
    {"key": "lucas", "label": "リュカ数"},
    {"key": "pell", "label": "ペル数"},
    {"key": "catalan", "label": "カタラン数"},
]

# math_flag_details のフラグ名 → propertyFilters キー
FLAG_NAME_TO_KEY = {
    "平方数": "square",
    "立方数": "cube",
    "三角数": "triangular",
    "フィボナッチ数": "fibonacci",
    "メルセンヌ数": "mersenne",
    "完全数": "perfect",
    "過剰数": "abundant",
    "不足数": "deficient",
    "半素数": "semiprime",
    "楔数": "sphenic",
    "ハーシャッド数": "harshad",
    "ハッピー数": "happy",
    "回文数": "palindrome",
    "回文素数": "palindromic_prime",
    "エマープ": "emirp",
    "双子素数": "twin_prime",
    "ソフィー・ジェルマン素数": "sophie_germain",
    "安全素数": "safe_prime",
    "高度合成数": "highly_composite",
    "階乗数": "factorial",
    "リュカ数": "lucas",
    "ペル数": "pell",
    "カタラン数": "catalan",
}

_PROP_LABELS = {d["key"]: d["label"] for d in PROPERTY_FILTER_DEFS}
_LORE_LABELS = {d["key"]: d["label"] for d in LORE_FILTER_DEFS}


def _build_record(n: int, lore: dict) -> dict:
    info = gen.build_info(n)

    # --- loreFilters ---
    lore_filters: list[str] = ["numerology"]  # 数秘・エンジェル・ヘブライ数字は全数に付与
    if (lore.get("notable_gematria") or {}).get(str(n)):
        lore_filters.append("gematria")
    entries = (lore.get("entries") or {}).get(str(n)) or []
    for cat in gen.LORE_CATEGORY_ORDER:
        if any(isinstance(e, dict) and e.get("cat") == cat for e in entries):
            lore_filters.append(cat)

    # --- propertyFilters ---
    property_filters: list[str] = []
    if n in (0, 1):
        property_filters.append("special")
    elif info.is_prime:
        property_filters.append("prime")
    else:
        property_filters.append("composite")
    property_filters.append("even" if info.is_even else "odd")
    for name, _detail in gen.math_flag_details(n, info):
        key = FLAG_NAME_TO_KEY.get(name)
        if key and key not in property_filters:
            property_filters.append(key)

    # --- snippets ---
    snippets: list[str] = []
    for e in entries:
        if isinstance(e, dict) and e.get("text"):
            snippets.append(e["text"])
            break

    # --- searchText ---
    tokens: list[str] = [
        str(n),
        f"{n:03d}",
        info.jp_kanji,
        info.jp_daiji,
        info.jp_reading,
        info.en_words,
    ]
    tokens.extend(_LORE_LABELS[k] for k in lore_filters if k in _LORE_LABELS)
    tokens.extend(_PROP_LABELS[k]
                  for k in property_filters if k in _PROP_LABELS)
    tokens.extend(snippets)
    search_text = " ".join(tokens).lower()

    return {
        "n": n,
        "id": f"{n:03d}",
        "title": f"{n}（{n:03d}）",
        "path": f"numbers/{n // 100}xx/{n:03d}.md",
        "loreFilters": lore_filters,
        "propertyFilters": property_filters,
        "snippets": snippets,
        "searchText": search_text,
    }


def build_viewer_index() -> dict:
    lore = gen._load_number_lore()
    return {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "filters": {
            "lore": LORE_FILTER_DEFS,
            "properties": PROPERTY_FILTER_DEFS,
        },
        "numbers": [_build_record(n, lore) for n in range(1000)],
    }


def write_viewer_index(output_path: Path = OUTPUT_PATH) -> Path:
    data = build_viewer_index()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return output_path


if __name__ == "__main__":
    path = write_viewer_index()
    print(f"wrote {path}")
