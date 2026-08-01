"""
Tests for build_candidates' extraction-stats tracking — verifies that
failed/empty sources are counted and surfaced rather than silently
dropped. No network or API keys needed.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.agents.orchestrator import build_candidates
from app.schemas import ProductInput, SourceRef


def _src(url):
    return SourceRef(url=url, source_type="webpage", authority_score=0.5)


def test_successful_and_failed_sources_are_counted_separately():
    extractions = [
        {"source": _src("https://good.com/a"), "data": {"title": "Widget", "category": None, "description": None, "specifications": {}, "image_urls": []}},
        {"source": _src("https://bad.com/b"), "data": {"title": None, "category": None, "description": None, "specifications": {}, "image_urls": [], "_error": "timeout"}},
        {"source": _src("https://empty.com/c"), "data": {"title": None, "category": None, "description": None, "specifications": {}, "image_urls": []}},
    ]
    product_input = ProductInput(mpn="X1", brand="Acme", description="A widget")
    candidates = build_candidates(extractions, product_input)
    stats = candidates["extraction_stats"]

    assert stats.sources_attempted == 3
    assert stats.sources_succeeded == 1
    assert stats.sources_failed == 2
    assert "https://bad.com/b" in stats.failed_urls
    assert "https://empty.com/c" in stats.failed_urls
    assert "https://good.com/a" not in stats.failed_urls


def test_all_sources_failing_still_falls_back_to_input_description():
    extractions = [
        {"source": _src("https://bad.com/a"), "data": {"title": None, "category": None, "description": None, "specifications": {}, "image_urls": [], "_error": "404"}},
    ]
    product_input = ProductInput(mpn="X1", brand="Acme", description="A fallback description")
    candidates = build_candidates(extractions, product_input)

    assert candidates["extraction_stats"].sources_failed == 1
    assert len(candidates["description"]) == 1
    assert candidates["description"][0]["value"] == "A fallback description"


def test_no_sources_at_all_does_not_crash():
    product_input = ProductInput(mpn="X1", brand="Acme", description="Standalone description")
    candidates = build_candidates([], product_input)

    assert candidates["extraction_stats"].sources_attempted == 0
    assert candidates["extraction_stats"].sources_failed == 0
    assert candidates["description"][0]["value"] == "Standalone description"


if __name__ == "__main__":
    test_successful_and_failed_sources_are_counted_separately()
    test_all_sources_failing_still_falls_back_to_input_description()
    test_no_sources_at_all_does_not_crash()
    print("All tests passed.")
