"""
Tests for the confidence scoring logic only — no network or API keys
needed. Run with: pytest tests/test_confidence.py
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.agents.confidence_agent import score_field
from app.schemas import SourceRef


def _src(url, authority):
    return SourceRef(url=url, source_type="webpage", authority_score=authority)


def test_two_agreeing_high_authority_sources_score_high():
    values = [
        {"value": "Dual Op-Amp", "source": _src("https://ti.com/x", 0.95), "method": "html_table"},
        {"value": "Dual Op-Amp", "source": _src("https://mouser.com/x", 0.7), "method": "html_table"},
    ]
    result = score_field(values)
    assert result.value == "Dual Op-Amp"
    assert result.confidence_band == "high"
    assert result.needs_review is False


def test_single_low_authority_source_scores_low_or_medium():
    values = [
        {"value": "Something", "source": _src("https://randomblog.com/x", 0.3), "method": "text_parse"},
    ]
    result = score_field(values)
    assert result.confidence < 0.75


def test_conflicting_values_prefer_higher_authority_but_cap_confidence():
    values = [
        {"value": "PDIP-8", "source": _src("https://ti.com/x", 0.95), "method": "html_table"},
        {"value": "SOIC-8", "source": _src("https://randomsite.com/x", 0.3), "method": "text_parse"},
    ]
    result = score_field(values)
    assert result.value == "PDIP-8"  # higher authority wins
    assert result.confidence < 0.95  # but conflict caps confidence


def test_empty_input_returns_low_confidence_needs_review():
    result = score_field([])
    assert result.value is None
    assert result.needs_review is True


if __name__ == "__main__":
    test_two_agreeing_high_authority_sources_score_high()
    test_single_low_authority_source_scores_low_or_medium()
    test_conflicting_values_prefer_higher_authority_but_cap_confidence()
    test_empty_input_returns_low_confidence_needs_review()
    print("All tests passed.")
