"""
Retrieval Agent
----------------
Given (mpn, brand, description), find candidate sources: manufacturer
pages, distributor listings, PDF datasheets. Ranks by a simple
authority heuristic so downstream agents can weight sources sensibly.
"""

import re

from app.schemas import SourceRef
from app.utils.search import web_search, build_queries
from app import config


# Distributor and aggregator sites that are useful for product sourcing.
DISTRIBUTOR_DOMAINS = [
    "digikey",
    "mouser",
    "grainger",
    "mcmaster",
    "rs-online",
    "farnell",
    "octopart",
    "findchips",
]

# Marketplace sites are deprioritized because their listings are
# generally less authoritative than manufacturer/distributor sources.
MARKETPLACE_DOMAINS = [
    "amazon",
    "ebay",
    "walmart",
    "toolnut",
    "acmetools",
]


def _brand_tokens(brand: str) -> list[str]:
    return [
        token
        for token in re.split(r"[^a-z0-9]+", brand.lower())
        if len(token) > 2
    ]


def _authority_score(url: str, brand: str) -> float:
    url_lower = url.lower()

    # Manufacturer/brand-specific pages are highly authoritative.
    if any(token in url_lower for token in _brand_tokens(brand)):
        return 0.95

    # PDF datasheets are generally high-trust sources.
    if url_lower.endswith(".pdf"):
        return 0.85

    # Marketplace listings are intentionally deprioritized.
    if any(domain in url_lower for domain in MARKETPLACE_DOMAINS):
        return 0.15

    # Distributor and aggregator listings are useful but below
    # manufacturer sources.
    if any(domain in url_lower for domain in DISTRIBUTOR_DOMAINS):
        return 0.7

    # Generic webpages receive the default score.
    return 0.4


def _source_type(url: str, brand: str) -> str:
    url_lower = url.lower()

    if url_lower.endswith(".pdf"):
        return "pdf_datasheet"

    if brand.lower().replace(" ", "") in url_lower:
        return "manufacturer_page"

    if any(domain in url_lower for domain in DISTRIBUTOR_DOMAINS):
        return "distributor_listing"

    return "webpage"


def find_sources(
    mpn: str,
    brand: str,
    description: str,
) -> list[SourceRef]:
    queries = build_queries(mpn, brand, description)

    seen_urls: set[str] = set()
    candidates: list[SourceRef] = []

    for query in queries:
        try:
            results = web_search(query, num_results=6)
        except Exception:
            # A single failed query shouldn't kill retrieval;
            # keep going with the remaining queries.
            continue

        for result in results:
            url = result.get("url", "")

            if not url or url in seen_urls:
                continue

            seen_urls.add(url)

            candidates.append(
                SourceRef(
                    url=url,
                    title=result.get("title"),
                    source_type=_source_type(url, brand),
                    authority_score=_authority_score(url, brand),
                )
            )

    candidates.sort(
        key=lambda source: source.authority_score,
        reverse=True,
    )

    return candidates[: config.MAX_SOURCES_TO_FETCH]