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

    if cache_path.exists() and not refresh:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
        items = raw.get("intros", {})
        if isinstance(items, dict):
            out: dict[int, str] = {}
            for k, v in items.items():
                try:
                    n = int(k)
                except ValueError:
                    continue
                if not isinstance(v, str):
                    continue
                out[n] = v
            return out

    titles = [str(n) for n in numbers]
    intros_by_title = fetch_intros_by_titles(titles)

    # Map back to number -> extract using normalized titles.
    out: dict[int, str] = {}
    for n in numbers:
        title = str(n)
        intro = intros_by_title.get(title)
        if intro and intro.extract:
            out[n] = intro.extract

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "meta": {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                "intros": {str(k): v for k, v in sorted(out.items())},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return out
