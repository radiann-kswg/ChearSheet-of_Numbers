from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
import os
from pathlib import Path
import re

from wikidata_cc0 import WikidataEnrichment, load_or_build_enrichment
from wikipedia_ja import (
    extract_wikipedia_facts,
    load_or_build_wikipedia_intros_for_numbers,
    load_or_build_wikipedia_property_sentences_for_numbers,
)


ROOT = Path(__file__).resolve().parents[1]
NUMBERS_DIR = ROOT / "numbers"


def _dedupe_preserve_order(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        out.append(line)
    return out


def _looks_like_number_wikipedia_intro(intro_extract: str) -> bool:
    # 一部の数字は同名の固有名詞等へリダイレクト/曖昧さ回避されうる。
    # 数の記事の冒頭には「自然数」「整数」等が含まれることが多いので、最低限の安全策として使う。
    return ("自然数" in intro_extract) or ("整数" in intro_extract)


def _split_math_prefix(text: str) -> tuple[str, str] | None:
    """Split a Wikipedia excerpt into (math_like_prefix, remainder).

    We do NOT modify the quote itself. Instead, we optionally add a separate
    line that re-states the excerpt with KaTeX formatting.

    Prefix stops at:
    - Japanese characters
    - Japanese punctuation (。 、)
    - Parentheses ( ( / （ ) to keep the math part clean
    """

    s = text.strip()
    if not s:
        return None

    def _is_japanese_char(ch: str) -> bool:
        code = ord(ch)
        return (
            (0x3040 <= code <= 0x30FF)  # Hiragana/Katakana
            or (0x4E00 <= code <= 0x9FFF)  # CJK Unified Ideographs
        )

    end = 0
    for i, ch in enumerate(s):
        # Stop at delimiters (keep '.'/',' because decimals are common).
        if ch in "。、(（":
            end = i
            break
        if _is_japanese_char(ch):
            end = i
            break
        if ch.isdigit() and i + 1 < len(s) and _is_japanese_char(s[i + 1]):
            if i > 0 and s[i - 1] == " ":
                end = i
                break
        end = i + 1

    # Trim trailing spaces from the prefix but keep remainder intact.
    prefix_end = end
    while prefix_end > 0 and s[prefix_end - 1] == " ":
        prefix_end -= 1
    prefix = s[:prefix_end]
    remainder = s[prefix_end:]

    if not prefix:
        return None

    # Avoid cases like "= 0." that are missing the left-hand side.
    if prefix.startswith("=") or prefix.startswith("＝"):
        return None

    # Must contain at least one digit and a math signal.
    if not re.search(r"\d", prefix):
        return None
    if not re.search(r"[=^×÷√π]", prefix):
        return None
    if len(prefix) < 6:
        return None
    return prefix, remainder


def _to_katex_math(expr: str) -> str:
    s = expr

    # Defensive normalization:
    # Some pipelines/tools may double-escape backslashes, resulting in strings like
    # "\\times" in the final Markdown. For KaTeX macros, a single backslash is enough.
    # We only collapse when the backslashes are immediately followed by a macro name
    # (alphabetic), so we don't touch LaTeX line breaks ("\\\\") if they ever appear.
    s = re.sub(r"\\{2,}(?=[A-Za-z])", r"\\", s)

    # Normalize characters.
    s = s.replace("×", r"\times")
    s = s.replace("÷", r"\div")
    s = s.replace("π", r"\pi")
    s = s.replace("…", r"\dots")
    s = s.replace("−", "-")  # U+2212

    # Root notations seen in Japanese Wikipedia excerpts.
    # Example: ^3√31 -> \sqrt[3]{31}
    # IMPORTANT: replacement strings in re.sub treat backslashes specially.
    # Use double backslash to emit a literal backslash for KaTeX macros.
    s = re.sub(r"\^(\d+)√\s*(\d+)", r"\\sqrt[\1]{\2}", s)
    # Example: √10 -> \sqrt{10}
    s = re.sub(r"√\s*(\d+)", r"\\sqrt{\1}", s)

    # Use braces for exponents, including negative ones.
    s = re.sub(r"\^(-?\d+)", r"^{\1}", s)

    # Keep ASCII spaces (KaTeX ignores extra spaces reasonably).
    return s.strip()


ELEMENTS_JA: list[str | None] = [
    None,
    "水素",
    "ヘリウム",
    "リチウム",
    "ベリリウム",
    "ホウ素",
    "炭素",
    "窒素",
    "酸素",
    "フッ素",
    "ネオン",
    "ナトリウム",
    "マグネシウム",
    "アルミニウム",
    "ケイ素",
    "リン",
    "硫黄",
    "塩素",
    "アルゴン",
    "カリウム",
    "カルシウム",
    "スカンジウム",
    "チタン",
    "バナジウム",
    "クロム",
    "マンガン",
    "鉄",
    "コバルト",
    "ニッケル",
    "銅",
    "亜鉛",
    "ガリウム",
    "ゲルマニウム",
    "ヒ素",
    "セレン",
    "臭素",
    "クリプトン",
    "ルビジウム",
    "ストロンチウム",
    "イットリウム",
    "ジルコニウム",
    "ニオブ",
    "モリブデン",
    "テクネチウム",
    "ルテニウム",
    "ロジウム",
    "パラジウム",
    "銀",
    "カドミウム",
    "インジウム",
    "スズ",
    "アンチモン",
    "テルル",
    "ヨウ素",
    "キセノン",
    "セシウム",
    "バリウム",
    "ランタン",
    "セリウム",
    "プラセオジム",
    "ネオジム",
    "プロメチウム",
    "サマリウム",
    "ユウロピウム",
    "ガドリニウム",
    "テルビウム",
    "ジスプロシウム",
    "ホルミウム",
    "エルビウム",
    "ツリウム",
    "イッテルビウム",
    "ルテチウム",
    "ハフニウム",
    "タンタル",
    "タングステン",
    "レニウム",
    "オスミウム",
    "イリジウム",
    "白金",
    "金",
    "水銀",
    "タリウム",
    "鉛",
    "ビスマス",
    "ポロニウム",
    "アスタチン",
    "ラドン",
    "フランシウム",
    "ラジウム",
    "アクチニウム",
    "トリウム",
    "プロトアクチニウム",
    "ウラン",
    "ネプツニウム",
    "プルトニウム",
    "アメリシウム",
    "キュリウム",
    "バークリウム",
    "カリホルニウム",
    "アインスタイニウム",
    "フェルミウム",
    "メンデレビウム",
    "ノーベリウム",
    "ローレンシウム",
    "ラザホージウム",
    "ドブニウム",
    "シーボーギウム",
    "ボーリウム",
    "ハッシウム",
    "マイトネリウム",
    "ダームスタチウム",
    "レントゲニウム",
    "コペルニシウム",
    "ニホニウム",
    "フレロビウム",
    "モスコビウム",
    "リバモリウム",
    "テネシン",
    "オガネソン",
]


HTTP_STATUS_CODES_REPO_INDEX = (
    "https://github.com/radiann-kswg/CheatSheet-of_HttpResponceDataCode/blob/main/index.md"
)
LIST_7400_WIKIPEDIA_EN = "https://en.wikipedia.org/wiki/List_of_7400-series_integrated_circuits"


# 代表的な 74xx の機能（シリーズ/メーカーで差異があるため、断定を避けて入口として提示）
LOGIC_74XX_HINTS: dict[int, str] = {
    0: "4回路 2入力 NAND（例: 74xx00）",
    2: "4回路 2入力 NOR（例: 74xx02）",
    4: "6回路 インバータ（NOT）（例: 74xx04）",
    8: "4回路 2入力 AND（例: 74xx08）",
    32: "4回路 2入力 OR（例: 74xx32）",
    74: "2回路 Dフリップフロップ（例: 74xx74）",
    86: "4回路 2入力 XOR（例: 74xx86）",
    125: "4回路 3ステート・バッファ（例: 74xx125）",
    138: "3→8 デコーダ/デマルチプレクサ（例: 74xx138）",
    139: "2回路 2→4 デコーダ/デマルチプレクサ（例: 74xx139）",
    151: "8→1 マルチプレクサ（例: 74xx151）",
    157: "4回路 2→1 マルチプレクサ（例: 74xx157）",
    161: "4ビット 同期バイナリ・カウンタ（例: 74xx161）",
    163: "4ビット 同期バイナリ・カウンタ（例: 74xx163）",
    165: "8ビット PISO シフトレジスタ（例: 74xx165）",
    173: "4ビット レジスタ（3ステート出力）（例: 74xx173）",
    174: "6ビット Dフリップフロップ（例: 74xx174）",
    191: "4ビット UP/DOWN カウンタ（例: 74xx191）",
    240: "8ビット バッファ/ラインドライバ（反転, 3ステート）（例: 74xx240）",
    244: "8ビット バッファ/ラインドライバ（3ステート）（例: 74xx244）",
    245: "8ビット 双方向トランシーバ（3ステート）（例: 74xx245）",
    273: "8ビット レジスタ（例: 74xx273）",
    374: "8ビット Dフリップフロップ（3ステート）（例: 74xx374）",
    393: "デュアル 4ビット リップルカウンタ（例: 74xx393）",
}


KANJI_DIGITS = {
    0: "零",
    1: "一",
    2: "二",
    3: "三",
    4: "四",
    5: "五",
    6: "六",
    7: "七",
    8: "八",
    9: "九",
}

DAIJI_DIGITS = {
    0: "零",
    1: "壹",
    2: "貳",
    3: "參",
    4: "肆",
    5: "伍",
    6: "陸",
    7: "柒",
    8: "捌",
    9: "玖",
}


EN_UNDER_20 = {
    0: "zero",
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
    11: "eleven",
    12: "twelve",
    13: "thirteen",
    14: "fourteen",
    15: "fifteen",
    16: "sixteen",
    17: "seventeen",
    18: "eighteen",
    19: "nineteen",
}

EN_TENS = {
    20: "twenty",
    30: "thirty",
    40: "forty",
    50: "fifty",
    60: "sixty",
    70: "seventy",
    80: "eighty",
    90: "ninety",
}


JP_DIGIT_READING = {
    0: "れい",
    1: "いち",
    2: "に",
    3: "さん",
    4: "よん",
    5: "ご",
    6: "ろく",
    7: "なな",
    8: "はち",
    9: "きゅう",
}


@dataclass(frozen=True)
class NumberInfo:
    n: int
    factorization: str
    is_prime: bool
    is_even: bool
    digit_sum: int
    num_divisors: int | None
    sum_divisors: int | None
    proper_divisor_sum: int | None
    abundance: str | None
    totient: int | None
    is_square: bool
    is_cube: bool
    is_triangular: bool
    is_fibonacci: bool
    is_mersenne: bool
    representations: dict[str, str]
    jp_kanji: str
    jp_daiji: str
    jp_reading: str
    en_words: str
    atomic_element: str | None


def is_prime(n: int) -> bool:
    if n <= 1:
        return False
    if n <= 3:
        return True
    if n % 2 == 0:
        return False
    limit = int(math.isqrt(n))
    for d in range(3, limit + 1, 2):
        if n % d == 0:
            return False
    return True


def prime_factorization(n: int) -> list[tuple[int, int]]:
    factors: list[tuple[int, int]] = []
    if n <= 1:
        return factors

    remaining = n
    count = 0
    while remaining % 2 == 0:
        remaining //= 2
        count += 1
    if count:
        factors.append((2, count))

    p = 3
    while p * p <= remaining:
        count = 0
        while remaining % p == 0:
            remaining //= p
            count += 1
        if count:
            factors.append((p, count))
        p += 2

    if remaining > 1:
        factors.append((remaining, 1))

    return factors


def format_factorization(n: int, factors: list[tuple[int, int]]) -> str:
    if n == 0:
        return "0"
    if n == 1:
        return "1"
    if not factors:
        return str(n)
    parts: list[str] = []
    for p, exp in factors:
        if exp == 1:
            parts.append(str(p))
        else:
            parts.append(f"{p}^{exp}")
    return " × ".join(parts)


def divisor_count_and_sum(factors: list[tuple[int, int]]) -> tuple[int, int]:
    # For n >= 2
    count = 1
    sigma = 1
    for p, exp in factors:
        count *= exp + 1
        sigma *= (p ** (exp + 1) - 1) // (p - 1)
    return count, sigma


def euler_totient(n: int, factors: list[tuple[int, int]]) -> int:
    if n == 0:
        return 0
    if n == 1:
        return 1
    result = n
    for p, _ in factors:
        result = result // p * (p - 1)
    return result


def is_perfect_square(n: int) -> bool:
    if n < 0:
        return False
    r = math.isqrt(n)
    return r * r == n


def is_perfect_cube(n: int) -> bool:
    if n < 0:
        return False
    r = round(n ** (1 / 3))
    return r * r * r == n


def is_triangular(n: int) -> bool:
    if n < 0:
        return False
    # 8n+1 is a square
    return is_perfect_square(8 * n + 1)


def is_fibonacci(n: int) -> bool:
    if n < 0:
        return False
    return is_perfect_square(5 * n * n + 4) or is_perfect_square(5 * n * n - 4)


def is_mersenne(n: int) -> bool:
    # n = 2^p - 1
    if n <= 0:
        return False
    x = n + 1
    return x & (x - 1) == 0


def to_roman(n: int) -> str | None:
    if not (1 <= n <= 3999):
        return None
    numerals = [
        (1000, "M"),
        (900, "CM"),
        (500, "D"),
        (400, "CD"),
        (100, "C"),
        (90, "XC"),
        (50, "L"),
        (40, "XL"),
        (10, "X"),
        (9, "IX"),
        (5, "V"),
        (4, "IV"),
        (1, "I"),
    ]
    remaining = n
    out: list[str] = []
    for value, symbol in numerals:
        while remaining >= value:
            out.append(symbol)
            remaining -= value
    return "".join(out)


def to_kanji_upto_999(n: int, digits: dict[int, str], ten: str, hundred: str) -> str:
    if n == 0:
        return digits[0]
    if not (0 <= n <= 999):
        raise ValueError("Supported range is 0..999")

    h = n // 100
    t = (n // 10) % 10
    u = n % 10

    parts: list[str] = []
    if h:
        if h == 1:
            parts.append(hundred)
        else:
            parts.append(digits[h] + hundred)
    if t:
        if t == 1:
            parts.append(ten)
        else:
            parts.append(digits[t] + ten)
    if u:
        parts.append(digits[u])
    return "".join(parts)


def japanese_reading_upto_999(n: int) -> str:
    if n == 0:
        return JP_DIGIT_READING[0]

    h = n // 100
    t = (n // 10) % 10
    u = n % 10

    out: list[str] = []

    if h:
        if h == 1:
            out.append("ひゃく")
        elif h == 3:
            out.append("さんびゃく")
        elif h == 6:
            out.append("ろっぴゃく")
        elif h == 8:
            out.append("はっぴゃく")
        else:
            out.append(JP_DIGIT_READING[h] + "ひゃく")

    if t:
        if t == 1:
            out.append("じゅう")
        else:
            out.append(JP_DIGIT_READING[t] + "じゅう")

    if u:
        out.append(JP_DIGIT_READING[u])

    return "".join(out)


def english_words_upto_999(n: int) -> str:
    if not (0 <= n <= 999):
        raise ValueError("Supported range is 0..999")
    if n < 20:
        return EN_UNDER_20[n]
    if n < 100:
        tens = (n // 10) * 10
        unit = n % 10
        if unit == 0:
            return EN_TENS[tens]
        return f"{EN_TENS[tens]}-{EN_UNDER_20[unit]}"

    hundreds = n // 100
    rest = n % 100
    if rest == 0:
        return f"{EN_UNDER_20[hundreds]} hundred"
    return f"{EN_UNDER_20[hundreds]} hundred {english_words_upto_999(rest)}"


def build_info(n: int) -> NumberInfo:
    factors = prime_factorization(n)
    factorization = format_factorization(n, factors)

    prime_flag = is_prime(n)
    even_flag = n % 2 == 0
    digit_sum = sum(int(ch) for ch in str(n))

    if n >= 1:
        if n == 1:
            num_divisors = 1
            sum_divisors = 1
            proper_divisor_sum = 0
        else:
            num_divisors, sum_divisors = divisor_count_and_sum(factors)
            proper_divisor_sum = sum_divisors - n
        if n == 0:
            abundance = None
        else:
            if sum_divisors == 2 * n:
                abundance = "完全数"
            elif sum_divisors > 2 * n:
                abundance = "過剰数"
            else:
                abundance = "不足数"
        totient = euler_totient(n, factors)
    else:
        num_divisors = None
        sum_divisors = None
        proper_divisor_sum = None
        abundance = None
        totient = None

    roman = to_roman(n)

    reps = {
        "2進": bin(n)[2:],
        "8進": oct(n)[2:],
        "16進": hex(n)[2:].upper(),
    }
    if roman is not None:
        reps["ローマ数字"] = roman

    jp_kanji = to_kanji_upto_999(n, KANJI_DIGITS, ten="十", hundred="百")
    jp_daiji = to_kanji_upto_999(n, DAIJI_DIGITS, ten="拾", hundred="佰")
    jp_reading = japanese_reading_upto_999(n)
    en_words = english_words_upto_999(n)

    atomic_element = ELEMENTS_JA[n] if 1 <= n < len(ELEMENTS_JA) else None

    return NumberInfo(
        n=n,
        factorization=factorization,
        is_prime=prime_flag,
        is_even=even_flag,
        digit_sum=digit_sum,
        num_divisors=num_divisors,
        sum_divisors=sum_divisors,
        proper_divisor_sum=proper_divisor_sum,
        abundance=abundance,
        totient=totient,
        is_square=is_perfect_square(n),
        is_cube=is_perfect_cube(n),
        is_triangular=is_triangular(n),
        is_fibonacci=is_fibonacci(n),
        is_mersenne=is_mersenne(n),
        representations=reps,
        jp_kanji=jp_kanji,
        jp_daiji=jp_daiji,
        jp_reading=jp_reading,
        en_words=en_words,
        atomic_element=atomic_element,
    )


def rel_link(from_path: Path, to_path: Path) -> str:
    return Path(os.path.relpath(to_path, start=from_path.parent)).as_posix()


def parse_only_numbers(spec: str) -> list[int]:
    # Examples: "444" / "0-99" / "444,42,100-120"
    spec = spec.strip()
    if not spec:
        raise ValueError("empty spec")

    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            start = int(a.strip())
            end = int(b.strip())
            if start > end:
                start, end = end, start
            for n in range(start, end + 1):
                if 0 <= n <= 999:
                    out.add(n)
        else:
            n = int(part)
            if 0 <= n <= 999:
                out.add(n)
    return sorted(out)


def number_file_path(n: int) -> Path:
    folder = f"{n // 100}xx"
    return NUMBERS_DIR / folder / f"{n:03d}.md"


def _format_wikidata_refs(refs: list[object], limit: int = 10) -> list[str]:
    # `WikidataRef` のように `.label` と `.url` を持つ型を想定
    shown = refs[:limit]
    lines = [f"- {getattr(r, 'label')}（{getattr(r, 'url')}）" for r in shown]
    remaining = len(refs) - len(shown)
    if remaining > 0:
        lines.append(f"- 他 {remaining} 件")
    return lines


def render_number_page(
    info: NumberInfo,
    wikidata: WikidataEnrichment | None,
    wikipedia_intros: dict[int, str] | None,
    wikipedia_properties: dict[int, list[str]] | None,
) -> str:
    n = info.n
    prev_path = number_file_path(n - 1) if n > 0 else None
    next_path = number_file_path(n + 1) if n < 999 else None

    here = number_file_path(n)

    nav_parts: list[str] = []
    if prev_path is not None:
        nav_parts.append(f"前: [{n-1:03d}]({rel_link(here, prev_path)})")
    if next_path is not None:
        nav_parts.append(f"次: [{n+1:03d}]({rel_link(here, next_path)})")

    category_bits: list[str] = []
    if info.is_prime:
        category_bits.append("素数")
    elif n in (0, 1):
        category_bits.append("特殊")
    else:
        category_bits.append("合成数")

    category_bits.append("偶数" if info.is_even else "奇数")

    flags: list[str] = []
    if info.is_square:
        flags.append("平方数")
    if info.is_cube:
        flags.append("立方数")
    if info.is_triangular:
        flags.append("三角数")
    if info.is_fibonacci:
        flags.append("フィボナッチ数")
    if info.is_mersenne:
        flags.append("メルセンヌ数")

    if info.abundance:
        flags.append(info.abundance)

    flag_text = " / ".join(flags) if flags else "（特記事項なし）"

    reps_lines = "\n".join([f"- **{k}**: `{v}`" for k, v in info.representations.items()])

    factorization_katex = _to_katex_math(info.factorization)
    math_lines: list[str] = [
        f"- **素因数分解**: ${factorization_katex}$",
        f"- **各位の和**: {info.digit_sum}",
    ]

    if n >= 1:
        math_lines.extend(
            [
                f"- **約数の個数**: {info.num_divisors}",
                f"- **約数の和**: {info.sum_divisors}",
                f"- **真の約数の和**: {info.proper_divisor_sum}",
                f"- **オイラーのトーシェント関数** $\\varphi({n})$: {info.totient}",
            ]
        )

    science_lines: list[str] = []
    if info.atomic_element is not None:
        # Wikipedia の各元素ページは安定しているので、最小限の一次資料リンクとして付ける
        science_lines.append(
            f"- **原子番号**: {info.atomic_element}（[元素](https://ja.wikipedia.org/wiki/{info.atomic_element})）"
        )

    if not science_lines:
        science_lines.append("- （要約可能な一次情報が見つかったら追記）")

    culture_lines: list[str] = [
        f"- **日本語（漢数字）**: {info.jp_kanji}",
        f"- **日本語（大字）**: {info.jp_daiji}",
        f"- **日本語（読み）**: {info.jp_reading}",
        f"- **英語**: {info.en_words}",
    ]

    wikipedia_points: list[str] = []
    # 可能な範囲で、Wikipedia「性質」を置き換え可能な“機械的に導ける要点”を入れる
    if info.is_prime:
        wikipedia_points.append("- 素数（Wikipediaの『性質』参照）")
    elif n in (0, 1):
        wikipedia_points.append("- 0/1 は数論上の扱いに注意（Wikipedia参照）")
    else:
        wikipedia_points.append("- 合成数（Wikipediaの『性質』参照）")

    if info.is_mersenne:
        wikipedia_points.append("- メルセンヌ数（$2^p-1$ 形）")
    if info.is_square:
        wikipedia_points.append("- 平方数")
    if info.is_cube:
        wikipedia_points.append("- 立方数")
    if info.is_triangular:
        wikipedia_points.append("- 三角数")
    if info.is_fibonacci:
        wikipedia_points.append("- フィボナッチ数")
    if info.abundance:
        wikipedia_points.append(f"- {info.abundance}（Wikipedia参照）")

    intro_extract = (wikipedia_intros or {}).get(n)
    if intro_extract and _looks_like_number_wikipedia_intro(intro_extract):
        facts = extract_wikipedia_facts(intro_extract)
        prime_index = facts.get("prime_index")
        if info.is_prime and isinstance(prime_index, int):
            wikipedia_points.append(f"- {prime_index}番目の素数として説明される（Wikipedia参照）")

        fib_index = facts.get("fibonacci_index")
        if info.is_fibonacci and isinstance(fib_index, int):
            wikipedia_points.append(f"- {fib_index}番目のフィボナッチ数として説明される（Wikipedia参照）")

        tri_index = facts.get("triangular_index")
        if info.is_triangular and isinstance(tri_index, int):
            wikipedia_points.append(f"- {tri_index}番目の三角数として説明される（Wikipedia参照）")

        perfect_index = facts.get("perfect_index")
        if info.abundance == "完全数" and isinstance(perfect_index, int):
            wikipedia_points.append(f"- {perfect_index}番目の完全数として説明される（Wikipedia参照）")

        terms = facts.get("terms")
        if isinstance(terms, list):
            skip_terms: set[str] = set()
            skip_terms.update(["素数", "合成数", "平方数", "立方数", "三角数", "フィボナッチ数", "メルセンヌ数"])
            if info.abundance:
                skip_terms.add(info.abundance)
            shown_terms = [t for t in terms if isinstance(t, str) and t not in skip_terms][:5]
            for t in shown_terms:
                wikipedia_points.append(f"- {t}（Wikipedia参照）")

        props = (wikipedia_properties or {}).get(n)
        if isinstance(props, list) and props:
            for s in props[:3]:
                if not isinstance(s, str) or not s.strip():
                    continue
                excerpt = s.strip()
                excerpt = re.sub(r"^\(\s*\)\s*", "", excerpt)
                excerpt = re.sub(r"^[（(]\s*[0-9一二三四五六七八九十]*\s*[)）]\s*", "", excerpt)
                omitted = False
                if len(excerpt) > 140:
                    excerpt = excerpt[:140].rstrip() + "…"
                    omitted = True
                split = _split_math_prefix(excerpt)
                if split:
                    prefix, remainder = split
                    normalized = _to_katex_math(prefix)
                    formatted_sentence = f"${normalized}${remainder}".strip()
                    notes: list[str] = ["表記を整形"]
                    if omitted:
                        notes.append("一部省略")
                    note_text = " / " + " / ".join(notes) if notes else ""
                    wikipedia_points.append(
                        f"- Wikipedia『性質』より（短い引用・整形）: 「{formatted_sentence}」（出典: https://ja.wikipedia.org/wiki/{n}#%E6%80%A7%E8%B3%AA / CC BY-SA{note_text}）"
                    )
                else:
                    note = "一部省略" if omitted else ""
                    wikipedia_points.append(
                        f"- Wikipedia『性質』より（短い引用）: 「{excerpt}」（出典: https://ja.wikipedia.org/wiki/{n}#%E6%80%A7%E8%B3%AA / CC BY-SA{(' / ' + note) if note else ''}）"
                    )

    other_points: list[str] = []
    if info.atomic_element is not None:
        other_points.append(
            f"- 原子番号 {n} の元素: {info.atomic_element}（Wikipedia『その他』参照）"
        )

    # 文化的に有名な関連（例）: 42
    if n == 42:
        other_points.extend(
            [
                "- 『銀河ヒッチハイク・ガイド』に関連して言及されることで有名（要点は Wikipedia 参照）",
                "- ルイス・キャロルとの関連が挙げられる（詳細は Wikipedia 参照）",
            ]
        )

    if intro_extract and _looks_like_number_wikipedia_intro(intro_extract):
        facts = extract_wikipedia_facts(intro_extract)
        first_sentence = facts.get("first_sentence")
        if isinstance(first_sentence, str) and first_sentence:
            # Keep it short: this is a *very* small excerpt.
            excerpt = first_sentence
            omitted = False
            if len(excerpt) > 120:
                excerpt = excerpt[:120].rstrip() + "…"
                omitted = True
            note = "一部省略" if omitted else ""
            # Attribution + license hint to stay CC BY-SA-friendly.
            other_points.append(
                f"- Wikipedia冒頭（短い引用）: 「{excerpt}」（出典: https://ja.wikipedia.org/wiki/{n} / CC BY-SA{(' / ' + note) if note else ''}）"
            )

    wikipedia_points = _dedupe_preserve_order(wikipedia_points)
    other_points = _dedupe_preserve_order(other_points)

    wikidata_number_lines: list[str] = []
    if wikidata is not None:
        item = wikidata.number_items.get(n)
        if item is not None:
            desc = f"（説明: {item.description_ja}）" if item.description_ja else ""
            wikidata_number_lines.append(f"- Wikidata: {item.url}{desc}")

    tech_code_lines: list[str] = []
    # HTTP status code (100-599)
    if 100 <= n <= 599:
        tech_code_lines.extend(
            [
                "### HTTP ステータスコード（該当する場合）",
                f"- この数字は HTTP ステータスコードとして用いられることがあります（意味・典型例は要約し、一次情報へリンクします）。",
                f"- MDN: https://developer.mozilla.org/ja/docs/Web/HTTP/Status/{n}",
                f"- 参照（チートシート）: {HTTP_STATUS_CODES_REPO_INDEX}",
            ]
        )

    if wikidata is not None:
        iso = wikidata.iso3166_numeric.get(n)
        if iso:
            tech_code_lines.append("### ISO 3166-1 numeric（国・地域の3桁コード）")
            tech_code_lines.append(
                "- ISO 3166-1 の数値コードとして、この数字が割り当てられている場合があります（一次情報は Wikidata へ）。"
            )
            tech_code_lines.extend(_format_wikidata_refs(iso, limit=10))

        tel = wikidata.tel_country_code.get(n)
        if tel:
            tech_code_lines.append("### 国番号（国際電話・E.164）")
            tech_code_lines.append(
                "- 国番号（国際電話識別番号）として、この数字が用いられる場合があります（一次情報は Wikidata へ）。"
            )
            tech_code_lines.extend(_format_wikidata_refs(tel, limit=10))

    # 7400 series logic number hints
    logic_hint = LOGIC_74XX_HINTS.get(n)
    logic_number = f"{n:02d}" if n < 100 else str(n)
    tech_code_lines.append("### 7400シリーズ（汎用ロジックICのロジック番号として）")
    if n < 100 or logic_hint is not None:
        tech_code_lines.append(
            f"- ロジック番号 `{logic_number}` は、`74xx{logic_number}`（例: `74HC{logic_number}` / `74LS{logic_number}` など）として現れることがあります。"
        )
    else:
        tech_code_lines.append(
            "- 7400シリーズのロジック番号は 2桁（00/04/74 など）や代表的な3桁（245/374 など）が中心です。"
        )
        tech_code_lines.append(
            f"- `{n}` が直接のロジック番号として一般的かはシリーズ/メーカーに依存するため、まず一覧で該当有無を確認してください。"
        )

    if logic_hint is not None:
        tech_code_lines.append(f"- 代表的な機能（目安）: {logic_hint}")
    tech_code_lines.append(f"- 一覧（一次情報への入口）: {LIST_7400_WIKIPEDIA_EN}")

    refs = [
        f"- Wikipedia（日本語）: https://ja.wikipedia.org/wiki/{n}",
        f"- Wikipedia（英語）: https://en.wikipedia.org/wiki/{n}",
        f"- OEIS 検索: https://oeis.org/search?q={n}&language=english",
    ]

    license_lines = [
        "- 本ページは CC BY-SA 4.0 のリポジトリ内コンテンツです。",
        "- Wikipedia のテキストは CC BY-SA（表示-継承）で提供されています。Wikipedia 本文を引用/転載する場合は、出典URL・ライセンス・変更有無を明記してください。",
        "- Wikidata の構造化データは CC0 です（本ページの一部データに利用）。",
    ]

    if nav_parts:
        nav = " / ".join(nav_parts)
        nav_line = f"{nav}\n"
    else:
        nav_line = ""

    title = f"# {n}（{n:03d}）\n"

    return "\n".join(
        [
            title,
            nav_line,
            f"> 分類: {' / '.join(category_bits)}\n",
            "## 概要\n",
            f"- **フラグ**: {flag_text}",
            "\n## 数学的性質\n",
            *math_lines,
            "\n## 表記\n",
            reps_lines,
            "\n## Wikipedia（要点）\n",
            "Wikipedia の『性質』『その他』は有用な入口ですが、本文の長文転載は避け、要点のみ要約してリンクします。\n",
            "### 性質（要約）\n",
            *wikipedia_points,
            "\n### その他（要約）\n",
            *(other_points if other_points else ["- （要約可能な関連が見つかったら追記）"]),
            "\n### Wikidata（CC0）\n",
            *(wikidata_number_lines if wikidata_number_lines else ["- （該当するWikidata項目が見つかったら追記）"]),
            "\n## 科学・技術（例）\n",
            *science_lines,
            "\n## 規格・コード（技術運用の例）\n",
            *tech_code_lines,
            "\n## 文化・言語（例）\n",
            *culture_lines,
            "\n## 参考\n",
            *refs,
            "\n## 出典・ライセンス\n",
            *license_lines,
            "",
        ]
    )


def render_index() -> str:
    lines: list[str] = []
    lines.append("# Index\n")
    lines.append("## 概要\n")
    lines.append(
        "0〜999 の数字について、数学的な性質（素因数分解・約数・表記など）と、科学/文化に関する一次情報（主に Wikipedia）への導線をまとめたチートシート集です。\n"
    )
    lines.append("- 本文は `numbers/` 配下（基本は 1 数字 = 1 ファイル）")
    lines.append("- 命名: `numbers/<hundreds>xx/<3桁>.md`（例: `numbers/0xx/031.md`）\n")

    lines.append("## 運用ヒント\n")
    lines.append("- まず `0xx/1xx/...` の範囲から探す")
    lines.append("- 各ページ末尾の Wikipedia リンクから一次情報へ\n")

    for h in range(10):
        start = h * 100
        end = start + 99
        lines.append(f"## {h}xx（{start:03d}〜{end:03d}）\n")
        lines.append("| " + " | ".join([f"{i}" for i in range(10)]) + " |")
        lines.append("| " + " | ".join(["---" for _ in range(10)]) + " |")
        for r in range(10):
            row: list[str] = []
            for c in range(10):
                n = start + r * 10 + c
                row.append(f"[{n:03d}](numbers/{h}xx/{n:03d}.md)")
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")

    return "\n".join(lines)


def render_readme() -> str:
    return "\n".join(
        [
            "# CheatSheet of Numbers (0-999)",
            "",
            "0〜999 の数字について、数学的な性質と、科学/文化に関する一次情報への導線をまとめたチートシート集です。",
            "",
            "- 入口: [index.md](index.md)",
            "- 個別ページ: `numbers/` 配下（基本は 1 数字 = 1 ファイル）",
            "- 一部の規格・コード情報は Wikidata（CC0）から自動取得して補強します",
            "- Wikipedia（日本語）の冒頭（概要）を短く要約して補強します（長文転載はしません）",
            "",
            "## 方針（公開に耐えるための注意）",
            "",
            "- 外部サイトの本文を長文転載しません（要約＋参照リンク中心）。",
            "- 引用する場合は短くし、出典 URL を必ず添えます。",
            "",
            "## ライセンス",
            "",
            "本リポジトリは **CC BY-SA 4.0** です。詳細は [LICENSE](LICENSE) を参照してください。",
            "",
            "- Wikidata の構造化データは CC0（パブリックドメイン相当）です。取得したデータの出典は各ページの Wikidata リンクを参照してください。",
            "",
            "## 生成について",
            "",
            "このリポジトリの `numbers/` 以下は、`tools/generate_numbers.py` で生成できます。",
            "",
            "```powershell",
            '"D:/VisualStudio Code Userfile/ChearSheet-of_Numbers/.venv/Scripts/python.exe" tools/generate_numbers.py',
            "```",
            "",
            "Wikidata 連携の制御（任意）:",
            "",
            "```powershell",
            '"D:/VisualStudio Code Userfile/ChearSheet-of_Numbers/.venv/Scripts/python.exe" tools/generate_numbers.py --no-wikidata',
            '"D:/VisualStudio Code Userfile/ChearSheet-of_Numbers/.venv/Scripts/python.exe" tools/generate_numbers.py --refresh-wikidata',
            "```",
            "",
            "Wikipedia（日本語）連携の制御（任意）:",
            "",
            "```powershell",
            '"D:/VisualStudio Code Userfile/ChearSheet-of_Numbers/.venv/Scripts/python.exe" tools/generate_numbers.py --no-wikipedia',
            '"D:/VisualStudio Code Userfile/ChearSheet-of_Numbers/.venv/Scripts/python.exe" tools/generate_numbers.py --refresh-wikipedia',
            "```",
            "",
            "## 参考リンク",
            "",
            "- Wikipedia 数の記事（例）: https://ja.wikipedia.org/wiki/31",
            "",
        ]
    )


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate number cheat sheets (0..999).")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use cache only; do not fetch from Wikipedia/Wikidata over the network.",
    )
    parser.add_argument(
        "--no-wikidata",
        action="store_true",
        help="Disable Wikidata(CC0) enrichment.",
    )
    parser.add_argument(
        "--refresh-wikidata",
        action="store_true",
        help="Refresh Wikidata cache (tools/_cache).",
    )
    parser.add_argument(
        "--no-wikipedia",
        action="store_true",
        help="Disable Japanese Wikipedia intro fetching.",
    )
    parser.add_argument(
        "--refresh-wikipedia",
        action="store_true",
        help="Refresh Japanese Wikipedia cache (tools/_cache).",
    )
    parser.add_argument(
        "--wikipedia-sections",
        action="store_true",
        help="Fetch Japanese Wikipedia section text (e.g., 性質) to extract non-trivial properties.",
    )
    parser.add_argument(
        "--refresh-wikipedia-sections",
        action="store_true",
        help="Refresh Japanese Wikipedia section cache (tools/_cache).",
    )
    parser.add_argument(
        "--only",
        type=str,
        default="",
        help="Generate only specified numbers: e.g. '444' or '0-99' or '444,42,100-120'.",
    )
    args = parser.parse_args()

    only_numbers: list[int] | None = None
    if args.only:
        only_numbers = parse_only_numbers(args.only)

    wikidata: WikidataEnrichment | None = None
    if not args.no_wikidata:
        try:
            cache_path = ROOT / "tools" / "_cache" / "wikidata_enrichment_v1.json"
            if args.offline:
                if cache_path.exists():
                    wikidata = load_or_build_enrichment(cache_path=cache_path, refresh=False)
            else:
                wikidata = load_or_build_enrichment(cache_path=cache_path, refresh=args.refresh_wikidata)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] Wikidata enrichment skipped: {e}")

    wikipedia_intros: dict[int, str] | None = None
    if not args.no_wikipedia:
        try:
            cache_path = ROOT / "tools" / "_cache" / "wikipedia_ja_intros_v1.json"
            wikipedia_intros = load_or_build_wikipedia_intros_for_numbers(
                cache_path=cache_path,
                refresh=args.refresh_wikipedia,
                numbers=only_numbers,
                offline=args.offline,
            )
        except Exception as e:  # noqa: BLE001
            print(f"[warn] Wikipedia intro fetch skipped: {e}")

    wikipedia_properties: dict[int, list[str]] | None = None
    if args.wikipedia_sections and wikipedia_intros is not None:
        try:
            cache_path = ROOT / "tools" / "_cache" / "wikipedia_ja_properties_v1.json"
            numbers = only_numbers if only_numbers is not None else list(range(1000))
            wikipedia_properties = load_or_build_wikipedia_property_sentences_for_numbers(
                cache_path=cache_path,
                refresh=args.refresh_wikipedia_sections,
                numbers=numbers,
                offline=args.offline,
            )
        except Exception as e:  # noqa: BLE001
            print(f"[warn] Wikipedia section fetch skipped: {e}")

    # Ensure base directories
    NUMBERS_DIR.mkdir(parents=True, exist_ok=True)
    for h in range(10):
        (NUMBERS_DIR / f"{h}xx").mkdir(parents=True, exist_ok=True)

    # Generate pages
    numbers_to_generate = only_numbers if only_numbers is not None else list(range(1000))
    for n in numbers_to_generate:
        info = build_info(n)
        write_file(
            number_file_path(n),
            render_number_page(info, wikidata, wikipedia_intros, wikipedia_properties),
        )

    # Entry points
    write_file(ROOT / "index.md", render_index())
    write_file(ROOT / "README.md", render_readme())


if __name__ == "__main__":
    main()
