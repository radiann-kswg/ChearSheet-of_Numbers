from __future__ import annotations

import gzip
import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path


WIKIPEDIA_JA_API_ENDPOINT = "https://ja.wikipedia.org/w/api.php"


@dataclass(frozen=True)
class WikipediaSection:
    index: str
    line: str


@dataclass(frozen=True)
class WikipediaIntro:
    title: str
    extract: str


def _http_get_json(
    url: str,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    timeout_sec: float = 20.0,
    max_retries: int = 3,
    base_sleep_sec: float = 1.0,
) -> dict:
    if params:
        q = urllib.parse.urlencode(params)
        full_url = f"{url}?{q}"
    else:
        full_url = url

    req_headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
        "User-Agent": "CheatSheet-of-Numbers/1.0 (Wikipedia intro fetch; contact: none)",
    }
    if headers:
        req_headers.update(headers)

    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            req = urllib.request.Request(full_url, headers=req_headers)
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                raw = resp.read()
                content_encoding = (resp.headers.get("Content-Encoding") or "").lower()

            if content_encoding == "gzip":
                raw = gzip.decompress(raw)

            return json.loads(raw.decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt >= max_retries:
                break
            time.sleep(base_sleep_sec * (2**attempt))

    raise RuntimeError(f"HTTP GET failed: {full_url} ({last_err})") from last_err


def _clean_text(text: str) -> str:
    # Normalize whitespace/newlines without changing meaning.
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _first_sentence_ja(text: str) -> str | None:
    text = _clean_text(text)
    if not text:
        return None

    # Prefer first sentence ending with '。'.
    if "。" in text:
        first = text.split("。", 1)[0].strip()
        if first:
            return first + "。"

    # Fallback: use first 100 chars.
    return text[:100].rstrip() + ("…" if len(text) > 100 else "")


def fetch_intros_by_titles(titles: list[str]) -> dict[str, WikipediaIntro]:
    # MediaWiki API: up to ~50 titles per request.
    out: dict[str, WikipediaIntro] = {}
    chunk_size = 50

    for i in range(0, len(titles), chunk_size):
        chunk = titles[i : i + chunk_size]
        titles_param = "|".join(chunk)

        data = _http_get_json(
            WIKIPEDIA_JA_API_ENDPOINT,
            params={
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "prop": "extracts",
                "exintro": "1",
                "explaintext": "1",
                "exsectionformat": "plain",
                "redirects": "1",
                "titles": titles_param,
            },
            timeout_sec=30.0,
        )

        pages = data.get("query", {}).get("pages", [])
        if isinstance(pages, list):
            for p in pages:
                if not isinstance(p, dict):
                    continue
                title = p.get("title")
                if not isinstance(title, str) or not title:
                    continue
                extract = p.get("extract")
                if not isinstance(extract, str):
                    extract = ""
                extract = _clean_text(extract)
                out[title] = WikipediaIntro(title=title, extract=extract)

        time.sleep(0.2)

    return out


def fetch_sections(title: str) -> list[WikipediaSection]:
    data = _http_get_json(
        WIKIPEDIA_JA_API_ENDPOINT,
        params={
            "action": "parse",
            "format": "json",
            "formatversion": "2",
            "prop": "sections",
            "redirects": "1",
            "page": title,
        },
        timeout_sec=30.0,
    )
    parse = data.get("parse")
    if not isinstance(parse, dict):
        return []
    sections = parse.get("sections")
    if not isinstance(sections, list):
        return []

    out: list[WikipediaSection] = []
    for s in sections:
        if not isinstance(s, dict):
            continue
        index = s.get("index")
        line = s.get("line")
        if isinstance(index, str) and isinstance(line, str):
            out.append(WikipediaSection(index=index, line=line))
    return out


def fetch_section_wikitext(title: str, section_index: str) -> str:
    data = _http_get_json(
        WIKIPEDIA_JA_API_ENDPOINT,
        params={
            "action": "parse",
            "format": "json",
            "formatversion": "2",
            "prop": "wikitext",
            "redirects": "1",
            "page": title,
            "section": section_index,
        },
        timeout_sec=30.0,
    )
    parse = data.get("parse")
    if not isinstance(parse, dict):
        return ""
    wt = parse.get("wikitext")
    if isinstance(wt, str):
        return wt
    return ""


def _strip_templates(text: str, max_passes: int = 10) -> str:
    # very small, non-recursive template stripping; good enough for our summaries
    prev = text
    for _ in range(max_passes):
        cur = re.sub(r"\{\{[^{}]*\}\}", " ", prev)
        if cur == prev:
            return cur
        prev = cur
    return prev


def _replace_common_templates(text: str) -> str:
    # Preserve a few common math-related templates before stripping the rest.
    text = re.sub(r"\{\{\s*sup\s*\|\s*([^{}|]+?)\s*\}\}", r"^\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\{\{\s*sub\s*\|\s*([^{}|]+?)\s*\}\}", r"_\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\{\{\s*overline\s*\|\s*([^{}|]+?)\s*\}\}", r"\1", text, flags=re.IGNORECASE)
    # Symbol templates
    text = re.sub(r"\{\{\s*π\s*\}\}", "π", text)
    text = re.sub(r"\{\{\s*pi\s*\}\}", "π", text, flags=re.IGNORECASE)
    return text


def wikitext_to_plain_text(wikitext: str) -> str:
    text = wikitext
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = re.sub(r"<ref[^>/]*/>", " ", text)
    text = re.sub(r"<ref[^>]*>.*?</ref>", " ", text, flags=re.DOTALL)
    text = _replace_common_templates(text)
    text = _strip_templates(text)
    # external links: [url label] -> label
    text = re.sub(r"\[(https?://\S+)\s+([^\]]+)\]", r"\2", text)
    text = re.sub(r"\[(https?://\S+)\]", " ", text)
    # internal links: [[A|B]] -> B, [[A]] -> A
    text = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    # bold/italic
    text = text.replace("'''''", "").replace("'''", "").replace("''", "")
    # headings/list markers
    text = re.sub(r"^=+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*=+$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[\*#;:]+\s*", "", text, flags=re.MULTILINE)
    # any remaining tags
    text = re.sub(r"<[^>]+>", " ", text)
    return _clean_text(text)


_PROPERTY_KEYWORDS = [
    "平方数",
    "立方数",
    "円周率",
    "近似",
    "誤差",
    "π",
    "√",
    "平方根",
    "円周",
    "点",
    "領域",
    "下",
    "末尾",
    "桁",
    "ゾロ目",
    "唯一",
    "ただ一つ",
    "のみ",
    "だけ",
    "合同",
    "剰余",
    "mod",
    "互いに",
]


def extract_property_sentences_from_plain_text(text: str, limit: int = 3) -> list[str]:
    text = _clean_text(text)
    if not text:
        return []

    parts = [p.strip() for p in text.split("。")]
    sentences: list[str] = []
    for p in parts:
        if not p:
            continue
        s = p + "。"
        # Drop only definitional lines about the number itself, not general math claims.
        if re.search(r"は\s*自然数(、また\s*整数において|また\s*整数において|または\s*整数において|である)", s):
            continue
        if len(s) < 18:
            continue
        sentences.append(s)

    def score(s: str) -> int:
        sc = 0
        for kw in _PROPERTY_KEYWORDS:
            if kw in s:
                sc += 3
        if "だけ" in s or "のみ" in s or "ただ" in s:
            sc += 2
        if any(ch in s for ch in ("÷", "/", "×", "^", "=", "√", "π")):
            sc += 2
        if len(s) >= 60:
            sc += 1
        return sc

    ranked = sorted(sentences, key=lambda s: (score(s), len(s)), reverse=True)
    out: list[str] = []
    seen: set[str] = set()
    for s in ranked:
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def extract_property_sentences_from_title(title: str, section_name_hint: str = "性質") -> list[str]:
    sections = fetch_sections(title)
    if not sections:
        return []

    target: WikipediaSection | None = None
    for s in sections:
        if s.line == section_name_hint or s.line.startswith(section_name_hint):
            target = s
            break
    if target is None:
        for s in sections:
            if section_name_hint in s.line:
                target = s
                break
    if target is None:
        return []

    wikitext = fetch_section_wikitext(title, target.index)
    if not wikitext:
        return []

    plain = wikitext_to_plain_text(wikitext)
    return extract_property_sentences_from_plain_text(plain)


_FACT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("prime_index", re.compile(r"(\d+)番目の素数")),
    ("fibonacci_index", re.compile(r"(\d+)番目のフィボナッチ数")),
    ("triangular_index", re.compile(r"(\d+)番目の三角数")),
    ("perfect_index", re.compile(r"(\d+)番目の完全数")),
]

_KEY_TERMS = [
    # 数論・整数論でよく見かける分類語（Wikipedia冒頭での言及を手がかりとして扱う）
    "メルセンヌ素数",
    "双子素数",
    "ソフィー・ジェルマン素数",
    "安全素数",
    "回文素数",
    "素数",
    "合成数",
    "平方数",
    "立方数",
    "三角数",
    "フィボナッチ数",
    "完全数",
    "過剰数",
    "不足数",
    "カプレカ数",
    "ナルシシスト数",
    "ハーシャッド数",
    "自己記述数",
]


def extract_wikipedia_facts(intro_extract: str) -> dict[str, object]:
    text = _clean_text(intro_extract)
    facts: dict[str, object] = {}

    for key, pattern in _FACT_PATTERNS:
        m = pattern.search(text)
        if m:
            try:
                facts[key] = int(m.group(1))
            except ValueError:
                pass

    found_terms = [term for term in _KEY_TERMS if term in text]
    if found_terms:
        facts["terms"] = found_terms

    sentence = _first_sentence_ja(text)
    if sentence:
        facts["first_sentence"] = sentence

    return facts


def load_or_build_wikipedia_intros_for_numbers(
    cache_path: Path,
    refresh: bool,
    numbers: list[int] | None = None,
) -> dict[int, str]:
    if numbers is None:
        numbers = list(range(1000))

    cached_all: dict[int, str] = {}
    if cache_path.exists():
        try:
            raw = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
        items = raw.get("intros", {})
        if isinstance(items, dict):
            for k, v in items.items():
                try:
                    n = int(k)
                except ValueError:
                    continue
                if not isinstance(v, str):
                    continue
                cached_all[n] = v

    requested_set = set(numbers)
    to_fetch: list[int]
    if refresh:
        to_fetch = list(requested_set)
    else:
        to_fetch = [n for n in requested_set if n not in cached_all]

    if to_fetch:
        titles = [str(n) for n in sorted(to_fetch)]
        intros_by_title = fetch_intros_by_titles(titles)
        for n in to_fetch:
            title = str(n)
            intro = intros_by_title.get(title)
            if intro and intro.extract:
                cached_all[n] = intro.extract

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "meta": {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                    "intros": {str(k): v for k, v in sorted(cached_all.items())},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    return {n: cached_all[n] for n in numbers if n in cached_all}


def load_or_build_wikipedia_property_sentences_for_numbers(
    cache_path: Path,
    refresh: bool,
    numbers: list[int],
) -> dict[int, list[str]]:
    cached_all: dict[int, list[str]] = {}
    if cache_path.exists():
        try:
            raw = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
        items = raw.get("properties", {})
        if isinstance(items, dict):
            for k, v in items.items():
                try:
                    n = int(k)
                except ValueError:
                    continue
                if not isinstance(v, list):
                    continue
                lines = [s for s in v if isinstance(s, str) and s.strip()]
                if lines:
                    cached_all[n] = lines

    requested_set = set(numbers)
    to_fetch: list[int]
    if refresh:
        to_fetch = list(requested_set)
    else:
        to_fetch = [n for n in requested_set if n not in cached_all]

    if to_fetch:
        for n in sorted(to_fetch):
            title = str(n)
            try:
                props = extract_property_sentences_from_title(title)
            except Exception:
                props = []
            if props:
                cached_all[n] = props
            time.sleep(0.2)

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "meta": {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                    "properties": {str(k): v for k, v in sorted(cached_all.items())},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    return {n: cached_all[n] for n in numbers if n in cached_all}
