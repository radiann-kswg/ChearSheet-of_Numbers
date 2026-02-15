from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
import gzip


WDQS_ENDPOINT = "https://query.wikidata.org/sparql"
WIKIDATA_API_ENDPOINT = "https://www.wikidata.org/w/api.php"


@dataclass(frozen=True)
class WikidataRef:
    label: str
    qid: str

    @property
    def url(self) -> str:
        return f"https://www.wikidata.org/wiki/{self.qid}"


@dataclass(frozen=True)
class WikidataNumberItem:
    qid: str
    description_ja: str | None

    @property
    def url(self) -> str:
        return f"https://www.wikidata.org/wiki/{self.qid}"


@dataclass(frozen=True)
class WikidataEnrichment:
    number_items: dict[int, WikidataNumberItem]
    iso3166_numeric: dict[int, list[WikidataRef]]
    tel_country_code: dict[int, list[WikidataRef]]


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
        "Accept": "application/sparql-results+json, application/json",
        "Accept-Encoding": "gzip, deflate",
        "User-Agent": "CheatSheet-of-Numbers/1.0 (Wikidata CC0 enrichment; contact: none)",
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


def wdqs_sparql(query: str, timeout_sec: float = 30.0) -> dict:
    return _http_get_json(
        WDQS_ENDPOINT,
        params={"format": "json", "query": query},
        timeout_sec=timeout_sec,
    )


def _entity_uri_to_qid(uri: str) -> str | None:
    # ex: http://www.wikidata.org/entity/Q42
    if "/entity/Q" not in uri:
        return None
    return uri.rsplit("/", 1)[-1]


def fetch_number_items_from_jawiki_titles(numbers: list[int]) -> dict[int, WikidataNumberItem]:
    # Action API: up to ~50 titles per request
    out: dict[int, WikidataNumberItem] = {}
    chunk_size = 50

    for i in range(0, len(numbers), chunk_size):
        chunk = numbers[i : i + chunk_size]
        titles = "|".join(str(n) for n in chunk)

        data = _http_get_json(
            WIKIDATA_API_ENDPOINT,
            params={
                "action": "wbgetentities",
                "format": "json",
                "formatversion": "2",
                "sites": "jawiki",
                "titles": titles,
                "props": "descriptions|sitelinks",
                "sitefilter": "jawiki",
                "languages": "ja",
                "maxlag": "5",
            },
            timeout_sec=30.0,
        )

        entities = data.get("entities", {})
        for ent in entities.values():
            qid = ent.get("id")
            if not qid or not qid.startswith("Q"):
                continue

            sitelinks = ent.get("sitelinks", {})
            jawiki = sitelinks.get("jawiki")
            if not jawiki:
                continue
            title = jawiki.get("title")
            if not title or not title.isdigit():
                continue
            n = int(title)

            desc = None
            descriptions = ent.get("descriptions")
            if isinstance(descriptions, dict):
                ja_desc = descriptions.get("ja")
                if isinstance(ja_desc, dict):
                    desc = ja_desc.get("value")

            out[n] = WikidataNumberItem(qid=qid, description_ja=desc)

        time.sleep(0.2)

    return out


def _sparql_bindings(rows: dict) -> list[dict[str, str]]:
    bindings = rows.get("results", {}).get("bindings", [])
    out: list[dict[str, str]] = []
    for row in bindings:
        flat: dict[str, str] = {}
        for k, v in row.items():
            if isinstance(v, dict) and "value" in v:
                flat[k] = str(v["value"])
        out.append(flat)
    return out


def fetch_iso3166_numeric_0_999() -> dict[int, list[WikidataRef]]:
    query = """PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT ?code ?country ?countryLabel WHERE {
  ?country wdt:P299 ?code .
  FILTER(REGEX(STR(?code), "^[0-9]{1,3}$"))
  BIND(xsd:integer(?code) AS ?num)
  FILTER(?num >= 0 && ?num <= 999)
  SERVICE wikibase:label { bd:serviceParam wikibase:language "ja,en". }
}
"""
    data = wdqs_sparql(query)

    out: dict[int, list[WikidataRef]] = {}
    for row in _sparql_bindings(data):
        code = row.get("code")
        country_uri = row.get("country")
        label = row.get("countryLabel")
        if not code or not country_uri or not label:
            continue
        if not code.isdigit():
            continue
        n = int(code)
        if not (0 <= n <= 999):
            continue

        qid = _entity_uri_to_qid(country_uri)
        if not qid:
            continue

        out.setdefault(n, []).append(WikidataRef(label=label, qid=qid))

    for k in out:
        out[k].sort(key=lambda r: r.label)

    return out


def fetch_tel_country_code_0_999_digits_only() -> dict[int, list[WikidataRef]]:
    query = """PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT ?code ?country ?countryLabel WHERE {
    ?country wdt:P474 ?code .
    FILTER(REGEX(STR(?code), "^\\\\+?[0-9]{1,3}$"))
    SERVICE wikibase:label { bd:serviceParam wikibase:language "ja,en". }
}
"""
    data = wdqs_sparql(query)

    out: dict[int, list[WikidataRef]] = {}
    for row in _sparql_bindings(data):
        code = row.get("code")
        country_uri = row.get("country")
        label = row.get("countryLabel")
        if not code or not country_uri or not label:
            continue
        code_digits = code.lstrip("+")
        if not code_digits.isdigit():
            continue
        n = int(code_digits)
        if not (0 <= n <= 999):
            continue

        qid = _entity_uri_to_qid(country_uri)
        if not qid:
            continue

        out.setdefault(n, []).append(WikidataRef(label=label, qid=qid))

    for k in out:
        out[k].sort(key=lambda r: r.label)

    return out


def load_or_build_enrichment(
    cache_path: Path,
    refresh: bool,
) -> WikidataEnrichment:
    if cache_path.exists() and not refresh:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
        number_items = {
            int(k): WikidataNumberItem(qid=v["qid"], description_ja=v.get("description_ja"))
            for k, v in raw.get("number_items", {}).items()
        }
        iso = {
            int(k): [WikidataRef(label=x["label"], qid=x["qid"]) for x in v]
            for k, v in raw.get("iso3166_numeric", {}).items()
        }
        tel = {
            int(k): [WikidataRef(label=x["label"], qid=x["qid"]) for x in v]
            for k, v in raw.get("tel_country_code", {}).items()
        }
        return WikidataEnrichment(number_items=number_items, iso3166_numeric=iso, tel_country_code=tel)

    numbers = list(range(1000))
    number_items = fetch_number_items_from_jawiki_titles(numbers)
    iso = fetch_iso3166_numeric_0_999()
    tel = fetch_tel_country_code_0_999_digits_only()

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "meta": {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                "number_items": {
                    str(k): {"qid": v.qid, "description_ja": v.description_ja}
                    for k, v in sorted(number_items.items())
                },
                "iso3166_numeric": {
                    str(k): [{"label": r.label, "qid": r.qid} for r in v]
                    for k, v in sorted(iso.items())
                },
                "tel_country_code": {
                    str(k): [{"label": r.label, "qid": r.qid} for r in v]
                    for k, v in sorted(tel.items())
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return WikidataEnrichment(number_items=number_items, iso3166_numeric=iso, tel_country_code=tel)
