"""
Cache
------
Simple in-memory cache keyed on (mpn, brand), with a TTL. Repeat lookups
of the same product within the TTL window skip the whole pipeline
(no wasted API quota, instant response).

Deliberately NOT a real distributed cache (Redis etc.) — for a single
hackathon-scale process, an in-memory dict is the right amount of
complexity. Swap this module out for Redis if this ever needs to run
across multiple worker processes.
"""
import time

_store: dict[str, tuple[float, dict]] = {}
TTL_SECONDS = 60 * 60  # 1 hour


def _key(mpn: str, brand: str) -> str:
    return f"{mpn.strip().lower()}|{brand.strip().lower()}"


def get(mpn: str, brand: str) -> dict | None:
    key = _key(mpn, brand)
    entry = _store.get(key)
    if not entry:
        return None
    timestamp, data = entry
    if time.time() - timestamp > TTL_SECONDS:
        del _store[key]
        return None
    return data


def set(mpn: str, brand: str, data: dict) -> None:
    _store[_key(mpn, brand)] = (time.time(), data)


def clear() -> None:
    _store.clear()