"""
Retrieval Agent
----------------
Given (mpn, brand, description), find candidate sources: manufacturer
pages, distributor listings, PDF datasheets. Ranks by a simple
authority heuristic so downstream agents can weight sources sensibly.
"""
from app.schemas import SourceRef
from app.utils.search import web_search, build_queries
from app import config


DISTRIBUTOR_DOMAINS = ["digikey", "mouser", "grainger", "mcmaster", "rs-online", "farnell"]


def _authority_score(url: str, brand: str) -> float:
    url_lower = url.lower()
    brand_token = brand.lower().replace(" ", "")
    if brand_token and brand_token in url_lower:
        return 0.95  # looks like the manufacturer's own domain
    if url_lower.endswith(".pdf"):
        return 0.85  # datasheets are high-trust regardless of host
    if any(d in url_lower for d in DISTRIBUTOR_DOMAINS):
        return 0.7
    return 0.4


def _source_type(url: str, brand: str) -> str:
    url_lower = url.lower()
    if url_lower.endswith(".pdf"):
        return "pdf_datasheet"
    if brand.lower().replace(" ", "") in url_lower:
        return "manufacturer_page"
    if any(d in url_lower for d in DISTRIBUTOR_DOMAINS):
        return "distributor_listing"
    return "webpage"


def find_sources(mpn: str, brand: str, description: str) -> list[SourceRef]:
    queries = build_queries(mpn, brand, description)
    seen_urls: set[str] = set()
    candidates: list[SourceRef] = []

    for query in queries:
        try:
            results = web_search(query, num_results=6)
        except Exception:
            # A single failed query shouldn't kill retrieval; keep going.
            continue
        for r in results:
            url = r.get("url", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            candidates.append(SourceRef(
                url=url,
                title=r.get("title"),
                source_type=_source_type(url, brand),
                authority_score=_authority_score(url, brand),
            ))

    candidates.sort(key=lambda s: s.authority_score, reverse=True)
    return candidates[: config.MAX_SOURCES_TO_FETCH]
