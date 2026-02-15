from __future__ import annotations

import gzip
import json
import math
import re
import time
import urllib.error
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

            sleep_sec = base_sleep_sec * (2**attempt)
            if isinstance(e, urllib.error.HTTPError):
                if e.code == 429:
                    retry_after = None
                    try:
                        retry_after = e.headers.get("Retry-After")
                    except Exception:  # noqa: BLE001
                        retry_after = None

                    if retry_after and str(retry_after).strip().isdigit():
                        sleep_sec = max(sleep_sec, float(str(retry_after).strip()))
                    else:
                        sleep_sec = max(sleep_sec, 30.0)
                elif e.code in (502, 503, 504):
                    sleep_sec = max(sleep_sec, 5.0)

            time.sleep(sleep_sec)

    raise RuntimeError(f"HTTP GET failed: {full_url} ({last_err})") from last_err


def _clean_text(text: str) -> str:
    # Normalize whitespace/newlines without changing meaning.
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _clean_text_preserve_newlines(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\t ]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [ln.strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines)


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


def wikitext_to_plain_text_keep_newlines(wikitext: str) -> str:
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
    return _clean_text_preserve_newlines(text)


_IMPORTANCE_THRESHOLD = 30
_MAX_SEARCH_QUERIES_PER_NUMBER = 6


def _load_pins_config(pins_path: Path) -> dict[int, dict[str, list[str]]]:
    """Load per-number pinned substrings for forced selection.

    File format (JSON):
    {
      "meta": {"version": 1},
      "pins": {
        "42": {"property": ["..."], "other": ["..."]}
      }
    }
    """

    if not pins_path.exists():
        return {}
    try:
        raw = json.loads(pins_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    pins = raw.get("pins", {})
    if not isinstance(pins, dict):
        return {}

    out: dict[int, dict[str, list[str]]] = {}
    for k, v in pins.items():
        try:
            n = int(k)
        except Exception:
            continue
        if not isinstance(v, dict):
            continue
        per: dict[str, list[str]] = {}
        for kind in ("property", "other"):
            items = v.get(kind, [])
            if not isinstance(items, list):
                continue
            cleaned: list[str] = []
            seen: set[str] = set()
            for s in items:
                if not isinstance(s, str):
                    continue
                s2 = _clean_text(s)
                if not s2 or s2 in seen:
                    continue
                seen.add(s2)
                cleaned.append(s2)
            if cleaned:
                per[kind] = cleaned
        if per:
            out[n] = per
    return out


def _load_threshold_overrides_config(overrides_path: Path) -> dict[int, dict[str, int]]:
    """Load per-number threshold overrides for importance selection.

    File format (JSON):
    {
      "meta": {"version": 1},
      "thresholds": {
        "57": {"property": 20, "other": 20}
      }
    }
    """

    if not overrides_path.exists():
        return {}
    try:
        raw = json.loads(overrides_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    thresholds = raw.get("thresholds", {})
    if not isinstance(thresholds, dict):
        return {}

    out: dict[int, dict[str, int]] = {}
    for k, v in thresholds.items():
        try:
            n = int(k)
        except Exception:
            continue
        if not isinstance(v, dict):
            continue
        per: dict[str, int] = {}
        for kind in ("property", "other"):
            val = v.get(kind)
            if isinstance(val, int):
                per[kind] = max(1, min(100, val))
        if per:
            out[n] = per
    return out


def _extract_scoring_term(text: str) -> str | None:
    """Extract a short term to estimate (fame, uniqueness).

    We prefer quoted titles (『...』/「...」) or a Katakana chunk.
    """

    s = _clean_text(text)
    if not s:
        return None

    m = re.search(r"[『「]([^『「』」]{2,40})[』」]", s)
    if m:
        term = m.group(1).strip()
        if 2 <= len(term) <= 40:
            return term

    # Katakana word/phrase often indicates a named entity.
    m = re.search(r"([ァ-ヴー]{4,30})", s)
    if m:
        term = m.group(1).strip()
        if 4 <= len(term) <= 30:
            return term

    # Common patterns for standards/codes.
    m = re.search(r"(ISO\s*\d{3,6}(?:-\d+)*)", s)
    if m:
        return m.group(1).replace(" ", "")
    m = re.search(r"(JIS\s*[A-Z]\s*\d{3,6})", s)
    if m:
        return _clean_text(m.group(1))

    return None


def _heuristic_property_score(s: str) -> int:
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


def _heuristic_other_score(s: str) -> int:
    sc = 0
    for kw in _OTHER_KEYWORDS:
        if kw in s:
            sc += 3
    if any(ch in s for ch in (":", "：")):
        sc += 2
    if re.search(r"[0-9]", s):
        sc += 1
    if re.search(r"[ァ-ヴー]{4,}", s):
        sc += 1
    return sc


def _load_searchhits_cache(cache_path: Path) -> dict[str, int]:
    if not cache_path.exists():
        return {}
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    items = raw.get("searchhits", {})
    if not isinstance(items, dict):
        return {}
    out: dict[str, int] = {}
    for k, v in items.items():
        if isinstance(k, str) and isinstance(v, int) and v >= 0:
            out[k] = v
    return out


def _save_searchhits_cache(cache_path: Path, cache: dict[str, int]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "meta": {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                "searchhits": dict(sorted(cache.items())),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _fetch_wikipedia_search_totalhits(query: str) -> int:
    q = _clean_text(query)
    if not q:
        return 0
    data = _http_get_json(
        WIKIPEDIA_JA_API_ENDPOINT,
        params={
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "list": "search",
            "srsearch": q,
            "srnamespace": "0",
            "srlimit": "1",
            "srinfo": "totalhits",
        },
        timeout_sec=30.0,
    )
    qi = data.get("query", {})
    if not isinstance(qi, dict):
        return 0
    si = qi.get("searchinfo", {})
    if not isinstance(si, dict):
        return 0
    th = si.get("totalhits")
    return int(th) if isinstance(th, int) and th >= 0 else 0


def _totalhits_to_fame_score(totalhits: int) -> int:
    # Map Wikipedia search total hits -> 1..10.
    # 1e5 hits roughly saturates at 10.
    if totalhits <= 0:
        return 1
    x = math.log10(totalhits + 1)
    score = 1 + int(round(min(1.0, x / 5.0) * 9))
    return max(1, min(10, score))


def _estimate_fame_score(
    term: str | None,
    *,
    offline: bool,
    searchhits_cache: dict[str, int],
    allow_fetch: bool,
) -> int:
    if term is None:
        return 4
    t = _clean_text(term)
    if not t:
        return 4
    if offline or not allow_fetch:
        # Offline fallback: titles/katakana tend to be notable.
        if re.search(r"[ァ-ヴー]{4,}", t):
            return 6
        if re.search(r"(ISO|JIS)", t):
            return 6
        return 5

    if t in searchhits_cache:
        return _totalhits_to_fame_score(searchhits_cache[t])

    try:
        totalhits = _fetch_wikipedia_search_totalhits(t)
    except Exception:
        totalhits = 0
    searchhits_cache[t] = totalhits
    time.sleep(0.1)
    return _totalhits_to_fame_score(totalhits)


def _estimate_uniqueness_score(term: str | None, term_freq: dict[str, int]) -> int:
    if term is None:
        return 4
    t = _clean_text(term)
    if not t:
        return 4
    freq = term_freq.get(t, 0)
    # freq=1 -> 10, freq~10 -> 7, freq~100 -> 5, freq~1000 -> 2
    v = math.log10(freq + 1)
    score = 11 - int(math.ceil(v * 3))
    return max(1, min(10, score))


def _build_term_frequency_from_items(items: dict[int, list[str]]) -> dict[str, int]:
    freq: dict[str, int] = {}
    for lines in items.values():
        for s in lines:
            if not isinstance(s, str):
                continue
            term = _extract_scoring_term(s)
            if not term:
                continue
            term = _clean_text(term)
            if not term:
                continue
            freq[term] = freq.get(term, 0) + 1
    return freq


def _select_by_importance(
    candidates: list[str],
    *,
    term_freq: dict[str, int],
    searchhits_cache: dict[str, int],
    offline: bool,
    limit: int,
    threshold: int,
    kind: str,
    pinned_substrings: list[str] | None = None,
) -> list[str]:
    # NOTE:
    # "limit" is treated as the *minimum* number of items to include.
    # If there are 4+ items meeting the importance threshold, we include all of them.
    if not candidates:
        return []

    cleaned: list[str] = []
    seen: set[str] = set()
    for s in candidates:
        if not isinstance(s, str):
            continue
        s2 = _clean_text(s)
        if not s2 or s2 in seen:
            continue
        seen.add(s2)
        cleaned.append(s2)

    if not cleaned:
        return []

    pinned_selected: list[str] = []
    if pinned_substrings:
        pins = [_clean_text(p) for p in pinned_substrings if isinstance(p, str)]
        pins = [p for p in pins if p]
        if pins:
            used: set[str] = set()
            for pin in pins:
                for s in cleaned:
                    if s in used:
                        continue
                    if pin in s:
                        used.add(s)
                        pinned_selected.append(s)
                        # 1 pin -> at most 1 selected line
                        break

    if pinned_selected:
        pinned_set = set(pinned_selected)
        cleaned = [s for s in cleaned if s not in pinned_set]

    if kind == "property":
        heur = _heuristic_property_score
    else:
        heur = _heuristic_other_score

    # Limit expensive search queries per number.
    ranked_for_search = sorted(cleaned, key=lambda s: (heur(s), len(s)), reverse=True)
    search_terms: set[str] = set()
    for s in ranked_for_search[:_MAX_SEARCH_QUERIES_PER_NUMBER]:
        term = _extract_scoring_term(s)
        if term:
            search_terms.add(_clean_text(term))

    scored: list[tuple[int, int, int, int, str]] = []
    for s in cleaned:
        term = _extract_scoring_term(s)
        fame = _estimate_fame_score(
            term,
            offline=offline,
            searchhits_cache=searchhits_cache,
            allow_fetch=(term is not None and _clean_text(term) in search_terms),
        )
        uniq = _estimate_uniqueness_score(term, term_freq)
        importance = max(1, min(100, fame * uniq))
        scored.append((importance, fame, uniq, len(s), s))

    scored.sort(key=lambda x: (x[0], x[1], x[2], x[3]), reverse=True)

    preferred = [s for importance, _, _, _, s in scored if importance >= threshold]
    # If enough items meet the threshold, include *all* of them.
    if len(preferred) >= limit:
        return pinned_selected + preferred
    # Fill with the next best even if below the threshold.
    out: list[str] = []
    used: set[str] = set()
    for s in preferred:
        if s not in used:
            used.add(s)
            out.append(s)
    for importance, _, _, _, s in scored:
        if s in used:
            continue
        used.add(s)
        out.append(s)
        if len(out) >= limit:
            break
    return pinned_selected + out


def _select_by_importance_legacy(
    candidates: list[str],
    *,
    term_freq: dict[str, int],
    searchhits_cache: dict[str, int],
    offline: bool,
    limit: int,
    threshold: int,
    kind: str,
    pinned_substrings: list[str] | None = None,
) -> list[str]:
    """Legacy selection behavior (cap at `limit`).

    - `limit` acts as a hard maximum.
    - Pins are also capped by `limit`.

    This is kept to allow side-by-side comparison in generated pages.
    """
    if not candidates:
        return []

    cleaned: list[str] = []
    seen: set[str] = set()
    for s in candidates:
        if not isinstance(s, str):
            continue
        s2 = _clean_text(s)
        if not s2 or s2 in seen:
            continue
        seen.add(s2)
        cleaned.append(s2)

    if not cleaned:
        return []

    pinned_selected: list[str] = []
    if pinned_substrings:
        pins = [_clean_text(p) for p in pinned_substrings if isinstance(p, str)]
        pins = [p for p in pins if p]
        if pins:
            used: set[str] = set()
            for pin in pins:
                for s in cleaned:
                    if s in used:
                        continue
                    if pin in s:
                        used.add(s)
                        pinned_selected.append(s)
                        if len(pinned_selected) >= limit:
                            break
                if len(pinned_selected) >= limit:
                    break

    if len(pinned_selected) >= limit:
        return pinned_selected[:limit]

    if pinned_selected:
        pinned_set = set(pinned_selected)
        cleaned = [s for s in cleaned if s not in pinned_set]

    if kind == "property":
        heur = _heuristic_property_score
    else:
        heur = _heuristic_other_score

    ranked_for_search = sorted(cleaned, key=lambda s: (heur(s), len(s)), reverse=True)
    search_terms: set[str] = set()
    for s in ranked_for_search[:_MAX_SEARCH_QUERIES_PER_NUMBER]:
        term = _extract_scoring_term(s)
        if term:
            search_terms.add(_clean_text(term))

    scored: list[tuple[int, int, int, int, str]] = []
    for s in cleaned:
        term = _extract_scoring_term(s)
        fame = _estimate_fame_score(
            term,
            offline=offline,
            searchhits_cache=searchhits_cache,
            allow_fetch=(term is not None and _clean_text(term) in search_terms),
        )
        uniq = _estimate_uniqueness_score(term, term_freq)
        importance = max(1, min(100, fame * uniq))
        scored.append((importance, fame, uniq, len(s), s))

    scored.sort(key=lambda x: (x[0], x[1], x[2], x[3]), reverse=True)

    preferred = [s for importance, _, _, _, s in scored if importance >= threshold]
    if len(preferred) >= limit:
        return pinned_selected + preferred[: (limit - len(pinned_selected))]

    out: list[str] = []
    used: set[str] = set()
    for s in preferred:
        if s not in used:
            used.add(s)
            out.append(s)
    for _, _, _, _, s in scored:
        if s in used:
            continue
        used.add(s)
        out.append(s)
        if len(out) >= limit:
            break

    return pinned_selected + out[: (limit - len(pinned_selected))]


def load_or_build_wikipedia_property_sentence_sets_for_numbers(
    cache_path: Path,
    refresh: bool,
    numbers: list[int],
    offline: bool = False,
) -> tuple[dict[int, list[str]], dict[int, list[str]]]:
    """Return (current, legacy) selections for Wikipedia '性質' essences."""
    cached_all: dict[int, list[str]] = {}
    cached_legacy: dict[int, list[str]] = {}
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

        legacy_items = raw.get("properties_legacy", {})
        if isinstance(legacy_items, dict):
            for k, v in legacy_items.items():
                try:
                    n = int(k)
                except ValueError:
                    continue
                if not isinstance(v, list):
                    continue
                lines = [s for s in v if isinstance(s, str) and s.strip()]
                if lines:
                    cached_legacy[n] = lines

    requested_set = set(numbers)
    to_fetch: list[int]
    if offline:
        to_fetch = []
    elif refresh:
        to_fetch = list(requested_set)
    else:
        missing_any = [n for n in requested_set if (n not in cached_all) or (n not in cached_legacy)]
        to_fetch = missing_any

    if to_fetch:
        searchhits_cache_path = cache_path.parent / "wikipedia_ja_searchhits_v1.json"
        searchhits_cache = _load_searchhits_cache(searchhits_cache_path)

        pins_path = cache_path.parent.parent / "wikipedia_ja_pins_v1.json"
        pins_config = _load_pins_config(pins_path)

        overrides_path = cache_path.parent.parent / "wikipedia_ja_importance_overrides_v1.json"
        threshold_overrides = _load_threshold_overrides_config(overrides_path)

        term_freq = _build_term_frequency_from_items(cached_all)
        fetched_candidates: dict[int, list[str]] = {}

        for n in sorted(to_fetch):
            title = str(n)
            try:
                candidates = extract_property_candidate_sentences_from_title(title)
            except Exception:
                candidates = []
            if candidates:
                fetched_candidates[n] = candidates
                for s in candidates:
                    term = _extract_scoring_term(s)
                    if term:
                        t = _clean_text(term)
                        if t:
                            term_freq[t] = term_freq.get(t, 0) + 1
            time.sleep(0.2)

        for n, candidates in fetched_candidates.items():
            pinned = pins_config.get(n, {}).get("property")
            threshold = threshold_overrides.get(n, {}).get("property", _IMPORTANCE_THRESHOLD)

            selected_current = _select_by_importance(
                candidates,
                term_freq=term_freq,
                searchhits_cache=searchhits_cache,
                offline=offline,
                limit=3,
                threshold=threshold,
                kind="property",
                pinned_substrings=pinned,
            )
            if selected_current:
                cached_all[n] = selected_current

            selected_legacy = _select_by_importance_legacy(
                candidates,
                term_freq=term_freq,
                searchhits_cache=searchhits_cache,
                offline=offline,
                limit=3,
                threshold=threshold,
                kind="property",
                pinned_substrings=pinned,
            )
            if selected_legacy:
                cached_legacy[n] = selected_legacy

        if not offline:
            _save_searchhits_cache(searchhits_cache_path, searchhits_cache)

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "meta": {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                    "properties": {str(k): v for k, v in sorted(cached_all.items())},
                    "properties_legacy": {str(k): v for k, v in sorted(cached_legacy.items())},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    cur = {n: cached_all[n] for n in numbers if n in cached_all}
    legacy = {n: cached_legacy[n] for n in numbers if n in cached_legacy}
    return cur, legacy


def load_or_build_wikipedia_other_item_sets_for_numbers(
    cache_path: Path,
    refresh: bool,
    numbers: list[int],
    offline: bool = False,
) -> tuple[dict[int, list[str]], dict[int, list[str]]]:
    """Return (current, legacy) selections for Wikipedia 'その他' essences."""
    cached_all: dict[int, list[str]] = {}
    cached_legacy: dict[int, list[str]] = {}
    if cache_path.exists():
        try:
            raw = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
        items = raw.get("others", {})
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

        legacy_items = raw.get("others_legacy", {})
        if isinstance(legacy_items, dict):
            for k, v in legacy_items.items():
                try:
                    n = int(k)
                except ValueError:
                    continue
                if not isinstance(v, list):
                    continue
                lines = [s for s in v if isinstance(s, str) and s.strip()]
                if lines:
                    cached_legacy[n] = lines

    requested_set = set(numbers)
    to_fetch: list[int]
    if offline:
        to_fetch = []
    elif refresh:
        to_fetch = list(requested_set)
    else:
        missing_any = [n for n in requested_set if (n not in cached_all) or (n not in cached_legacy)]
        to_fetch = missing_any

    if to_fetch:
        searchhits_cache_path = cache_path.parent / "wikipedia_ja_searchhits_v1.json"
        searchhits_cache = _load_searchhits_cache(searchhits_cache_path)

        pins_path = cache_path.parent.parent / "wikipedia_ja_pins_v1.json"
        pins_config = _load_pins_config(pins_path)

        overrides_path = cache_path.parent.parent / "wikipedia_ja_importance_overrides_v1.json"
        threshold_overrides = _load_threshold_overrides_config(overrides_path)

        term_freq = _build_term_frequency_from_items(cached_all)
        fetched_candidates: dict[int, list[str]] = {}

        for n in sorted(to_fetch):
            title = str(n)
            try:
                candidates = extract_other_candidate_items_from_title(title)
            except Exception:
                candidates = []
            if candidates:
                fetched_candidates[n] = candidates
                for s in candidates:
                    term = _extract_scoring_term(s)
                    if term:
                        t = _clean_text(term)
                        if t:
                            term_freq[t] = term_freq.get(t, 0) + 1
            time.sleep(0.2)

        for n, candidates in fetched_candidates.items():
            pinned = pins_config.get(n, {}).get("other")
            threshold = threshold_overrides.get(n, {}).get("other", _IMPORTANCE_THRESHOLD)

            selected_current = _select_by_importance(
                candidates,
                term_freq=term_freq,
                searchhits_cache=searchhits_cache,
                offline=offline,
                limit=3,
                threshold=threshold,
                kind="other",
                pinned_substrings=pinned,
            )
            if selected_current:
                cached_all[n] = selected_current

            selected_legacy = _select_by_importance_legacy(
                candidates,
                term_freq=term_freq,
                searchhits_cache=searchhits_cache,
                offline=offline,
                limit=3,
                threshold=threshold,
                kind="other",
                pinned_substrings=pinned,
            )
            if selected_legacy:
                cached_legacy[n] = selected_legacy

        if not offline:
            _save_searchhits_cache(searchhits_cache_path, searchhits_cache)

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "meta": {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                    "others": {str(k): v for k, v in sorted(cached_all.items())},
                    "others_legacy": {str(k): v for k, v in sorted(cached_legacy.items())},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    cur = {n: cached_all[n] for n in numbers if n in cached_all}
    legacy = {n: cached_legacy[n] for n in numbers if n in cached_legacy}
    return cur, legacy


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


def extract_property_candidate_sentences_from_plain_text(text: str, max_candidates: int = 12) -> list[str]:
    text = _clean_text(text)
    if not text:
        return []

    parts = [p.strip() for p in text.split("。")]
    sentences: list[str] = []
    for p in parts:
        if not p:
            continue
        s = p + "。"
        if re.search(r"は\s*自然数(、また\s*整数において|また\s*整数において|または\s*整数において|である)", s):
            continue
        if len(s) < 18:
            continue
        if len(s) > 280:
            continue
        sentences.append(s)

    ranked = sorted(sentences, key=lambda s: (_heuristic_property_score(s), len(s)), reverse=True)
    out: list[str] = []
    seen: set[str] = set()
    for s in ranked:
        s2 = _clean_text(s)
        if not s2 or s2 in seen:
            continue
        seen.add(s2)
        out.append(s2)
        if len(out) >= max_candidates:
            break
    return out


def extract_property_candidate_sentences_from_title(title: str, section_name_hint: str = "性質") -> list[str]:
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
    return extract_property_candidate_sentences_from_plain_text(plain)


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


_OTHER_KEYWORDS = [
    "原子番号",
    "元素",
    "作品",
    "小説",
    "映画",
    "アニメ",
    "ゲーム",
    "漫画",
    "曲",
    "アルバム",
    "誕生",
    "事件",
    "事故",
    "条約",
    "規格",
    "コード",
]


def extract_other_items_from_plain_text(text: str, limit: int = 3) -> list[str]:
    text = _clean_text_preserve_newlines(text)
    if not text:
        return []

    candidates: list[str] = []
    for line in text.split("\n"):
        if not line:
            continue
        # split into sentences as well; keep the original line if it looks list-like
        parts = [p.strip() for p in re.split(r"[。]", line) if p.strip()]
        if parts:
            for p in parts:
                candidates.append(p + "。")
        else:
            candidates.append(line)

    cleaned: list[str] = []
    for s in candidates:
        s = _clean_text(s)
        if not s:
            continue
        if re.search(r"は\s*自然数(、また\s*整数において|また\s*整数において|または\s*整数において|である)", s):
            continue
        if len(s) < 14:
            continue
        if len(s) > 220:
            continue
        cleaned.append(s)

    def score(s: str) -> int:
        sc = 0
        for kw in _OTHER_KEYWORDS:
            if kw in s:
                sc += 3
        if any(ch in s for ch in (":", "：")):
            sc += 2
        if re.search(r"[0-9]", s):
            sc += 1
        if re.search(r"[ァ-ヴー]{4,}", s):
            sc += 1
        return sc

    ranked = sorted(cleaned, key=lambda s: (score(s), -len(s)), reverse=True)
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


def extract_other_candidate_items_from_plain_text(text: str, max_candidates: int = 16) -> list[str]:
    text = _clean_text_preserve_newlines(text)
    if not text:
        return []

    candidates: list[str] = []
    for line in text.split("\n"):
        if not line:
            continue
        parts = [p.strip() for p in re.split(r"[。]", line) if p.strip()]
        if parts:
            for p in parts:
                candidates.append(p + "。")
        else:
            candidates.append(line)

    cleaned: list[str] = []
    for s in candidates:
        s = _clean_text(s)
        if not s:
            continue
        if re.search(r"は\s*自然数(、また\s*整数において|また\s*整数において|または\s*整数において|である)", s):
            continue
        if len(s) < 14:
            continue
        if len(s) > 220:
            continue
        cleaned.append(s)

    ranked = sorted(cleaned, key=lambda s: (_heuristic_other_score(s), -len(s)), reverse=True)
    out: list[str] = []
    seen: set[str] = set()
    for s in ranked:
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= max_candidates:
            break
    return out


def extract_other_candidate_items_from_title(title: str, section_name_hint: str = "その他") -> list[str]:
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

    plain = wikitext_to_plain_text_keep_newlines(wikitext)
    return extract_other_candidate_items_from_plain_text(plain)


def extract_other_items_from_title(title: str, section_name_hint: str = "その他") -> list[str]:
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

    plain = wikitext_to_plain_text_keep_newlines(wikitext)
    return extract_other_items_from_plain_text(plain)


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
    offline: bool = False,
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
    if offline:
        to_fetch = []
    elif refresh:
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
    offline: bool = False,
) -> dict[int, list[str]]:
    cur, _legacy = load_or_build_wikipedia_property_sentence_sets_for_numbers(
        cache_path=cache_path,
        refresh=refresh,
        numbers=numbers,
        offline=offline,
    )
    return cur


def load_or_build_wikipedia_other_items_for_numbers(
    cache_path: Path,
    refresh: bool,
    numbers: list[int],
    offline: bool = False,
) -> dict[int, list[str]]:
    cur, _legacy = load_or_build_wikipedia_other_item_sets_for_numbers(
        cache_path=cache_path,
        refresh=refresh,
        numbers=numbers,
        offline=offline,
    )
    return cur
