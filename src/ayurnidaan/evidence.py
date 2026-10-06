"""Literature evidence from Europe PMC (covers PubMed/MEDLINE + PMC; free REST API).

Google Scholar has no API and its terms forbid scraping, so Europe PMC is the
literature source. For every distinct disease name we record:

* ``hits_all`` / ``hits_india``  - papers mentioning the disease, overall and with India
  in the title/abstract or an author affiliation. Their ratio, relative to India's
  baseline share of the literature, is the *regional relevance* prior (diseases absent
  from India - Chagas, Lyme, Rocky Mountain spotted fever - sit far below it);
* ``hits_ayurveda`` and the top papers on the disease AND Ayurveda - shown to
  practitioners as the evidence base, with year, journal, citations and a link.

The crawl is resumable (cache file), rate-limited and retried; it is a build step, so
the running API never calls Europe PMC.
"""

from __future__ import annotations

import json
import math
import re
import time
import urllib.parse
from pathlib import Path

from .http import get_json
from .logging_utils import get_logger

log = get_logger(__name__)
API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
INDIA_BASELINE_SHARE = 0.03  # India's approximate share of biomedical literature (measured)


def _get(query: str, page_size: int = 1, sort: str | None = None, retries: int = 4) -> dict:
    params = {"query": query, "format": "json", "pageSize": page_size, "resultType": "lite"}
    if sort:
        params["sort"] = sort
    url = f"{API}?{urllib.parse.urlencode(params)}"
    for attempt in range(retries):
        try:
            return get_json(url, timeout=30)
        except Exception as exc:  # network blips, 429/5xx
            wait = 2**attempt
            log.warning(
                "europepmc retry", fields={"attempt": attempt, "wait": wait, "err": str(exc)}
            )
            time.sleep(wait)
    raise RuntimeError(f"Europe PMC failed for {query!r}")


def _phrase(name: str) -> str:
    return '"' + name.replace('"', "") + '"'


def fetch_disease(name: str) -> dict:
    p = _phrase(name)
    all_hits = _get(f"TITLE_ABS:{p}").get("hitCount", 0)
    india = _get(f"TITLE_ABS:{p} AND (TITLE_ABS:India OR AFF:India)").get("hitCount", 0)
    ayur = _get(
        f"TITLE_ABS:{p} AND (TITLE_ABS:Ayurveda OR TITLE_ABS:Ayurvedic)",
        page_size=5,
        sort="CITED desc",
    )
    papers = [
        {
            "title": r.get("title"),
            "year": r.get("pubYear"),
            "journal": r.get("journalTitle"),
            "cited_by": r.get("citedByCount", 0),
            "pmid": r.get("pmid"),
            "doi": r.get("doi"),
            "url": f"https://europepmc.org/article/{r.get('source')}/{r.get('id')}",
        }
        for r in ayur.get("resultList", {}).get("result", [])
    ]
    return {
        "hits_all": all_hits,
        "hits_india": india,
        "hits_ayurveda": ayur.get("hitCount", 0),
        "top_ayurveda_papers": papers,
    }


def crawl(names: list[str], cache_path: Path, delay: float = 0.25) -> dict:
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    todo = [n for n in dict.fromkeys(names) if n and n not in cache]
    log.info("evidence crawl", fields={"cached": len(cache), "todo": len(todo)})
    for i, name in enumerate(todo, 1):
        try:
            cache[name] = fetch_disease(name)
        except RuntimeError as exc:
            log.warning("evidence skipped", fields={"name": name, "err": str(exc)})
            continue
        if i % 25 == 0 or i == len(todo):
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
            )
            log.info("evidence progress", fields={"done": i, "of": len(todo)})
        time.sleep(delay)
    return cache


def regional_weight(entry: dict | None, min_hits: int = 30) -> float:
    """sqrt-tempered India relevance: 1.0 at or above India's baseline literature share.

    Too few papers overall -> no evidence either way -> 1.0 (never penalise the unknown)."""
    if not entry or entry["hits_all"] < min_hits:
        return 1.0
    share = entry["hits_india"] / entry["hits_all"]
    return round(max(0.2, min(1.0, math.sqrt(share / INDIA_BASELINE_SHARE))), 4)


def query_name(condition: dict) -> str:
    """Literature query for a condition: the modern KB name, or the first part of a
    classical condition's modern equivalent ("Haemangioma / Blood tumour" -> "Haemangioma")."""
    modern = condition["source"] == "condition_kb_modern"
    text = str(condition["name"] if modern else condition["modern_equivalent"])
    text = re.split(r"\s*\(", text)[0]
    parts = [p.strip() for p in text.split("/") if p.strip()]
    # "Acute/chronic suppurative otitis media": skip qualifier-only fragments
    meaningful = [p for p in parts if p.casefold() not in QUALIFIERS]
    return (meaningful or parts or [text])[0].strip()


QUALIFIERS = {"acute", "chronic", "mild", "severe", "early", "late", "recurrent", "general"}


_ENDEMIC_PATTERN = re.compile(
    # "-iasis" is parasitic except psoriasis, (nephro/chole)lithiasis, hypochondriasis
    r"virus|viral|fever|(?<!psor)(?<!lith)(?<!ondr)iasis|infection|bacterial|plague|pox|typhus|"
    r"malaria|leprosy|"
    r"tuberculosis|mycosis|fung|worm|parasit|tick|pinta|yaws|tularemia|cholera|"
    r"encephalitis|poisoning|disease of|borrelia|rickett|leishman|trypanosom|ebola|zika|"
    r"dengue|chikungunya|lyme|chagas|toxo|amoeb|amebi|giardi|cysticerc|hydatid",
    re.IGNORECASE,
)


def is_endemic_type(name: str) -> bool:
    """Infectious / vector-borne / environmental-toxin conditions, where geography decides
    exposure and the regional-relevance prior applies."""
    return bool(_ENDEMIC_PATTERN.search(name))
