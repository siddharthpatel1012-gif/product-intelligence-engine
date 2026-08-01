"""
Pluggable web search client.

SEARCH_PROVIDER in .env picks the primary provider ("serper" or "tavily").
If the primary provider errors or returns zero results, and the OTHER
provider has a key configured, this automatically falls back to it —
so a single provider outage/quota issue doesn't kill retrieval entirely.
"""
import requests
from app import config


def web_search(query: str, num_results: int = 8) -> list[dict]:
    """
    Returns a list of {title, url, snippet} dicts. Tries the configured
    primary provider first; falls back to the other provider (if its key
    is set) on error or empty results.
    """
    primary, fallback = _serper_search, _tavily_search
    primary_key, fallback_key = config.SERPER_API_KEY, config.TAVILY_API_KEY
    if config.SEARCH_PROVIDER == "tavily":
        primary, fallback = _tavily_search, _serper_search
        primary_key, fallback_key = config.TAVILY_API_KEY, config.SERPER_API_KEY

    if primary_key:
        try:
            results = primary(query, num_results)
            if results:
                return results
        except Exception as e:
            print(f"[search] primary provider failed for {query!r}: {e}")

    if fallback_key:
        try:
            return fallback(query, num_results)
        except Exception as e:
            print(f"[search] fallback provider also failed for {query!r}: {e}")

    return []


def _serper_search(query: str, num_results: int) -> list[dict]:
    if not config.SERPER_API_KEY:
        raise RuntimeError("SERPER_API_KEY not set in .env")
    resp = requests.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": config.SERPER_API_KEY, "Content-Type": "application/json"},
        json={"q": query, "num": num_results},
        timeout=config.REQUEST_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    data = resp.json()
    results = []
    for item in data.get("organic", [])[:num_results]:
        results.append({
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "snippet": item.get("snippet", ""),
        })
    return results


def _tavily_search(query: str, num_results: int) -> list[dict]:
    if not config.TAVILY_API_KEY:
        raise RuntimeError("TAVILY_API_KEY not set in .env")
    resp = requests.post(
        "https://api.tavily.com/search",
        json={
            "api_key": config.TAVILY_API_KEY,
            "query": query,
            "max_results": num_results,
        },
        timeout=config.REQUEST_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    data = resp.json()
    results = []
    for item in data.get("results", [])[:num_results]:
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("content", ""),
        })
    return results


def build_queries(mpn: str, brand: str, description: str) -> list[str]:
    """
    Multiple targeted queries beat one broad query — datasheet PDFs and
    distributor listings tend to rank for different phrasings. More
    queries = more distinct candidate sources = better odds that at
    least a few actually yield extractable data (some sites 403 bots,
    some pages are thin — casting a wider net compensates for that).
    """
    brand_domain = brand.lower().replace(" ", "").replace(".", "")
    return [
        f'"{mpn}" {brand} datasheet filetype:pdf',
        f'"{mpn}" {brand} specifications',
        f'{brand} {mpn} {description}',
        f'"{mpn}" site:{brand_domain}.com',
        f'"{mpn}" datasheet pdf',
        f'"{mpn}" buy distributor',
        f'"{mpn}" {brand} datasheet -filetype:pdf',
    ]