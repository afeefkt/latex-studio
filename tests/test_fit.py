# ── Job-fit scorer tests ──
#
# The scorer decides whether Afeef spends an evening on an application, so the
# calibration matters as much as the arithmetic. These lock in the band edges.
# Thresholds: STRONG >= 55%, STRETCH 35-54%, SKIP < 35%.

import pytest

from app.content import score_fit

REQS = [
    {"phrase": "AUTOSAR Classic", "category": "skill"},
    {"phrase": "ISO 26262", "category": "skill"},
    {"phrase": "MATLAB/Simulink", "category": "tool"},
    {"phrase": "DO-254", "category": "certification"},
    {"phrase": "German B2", "category": "language"},
]


def m(phrase, conf):
    return {"jd_phrase": phrase, "confidence": conf}


def test_no_requirements_is_unknown():
    r = score_fit([], [], [])
    assert r["band"] == "UNKNOWN"
    assert r["score"] == 0


def test_full_match_is_strong():
    matched = [m("AUTOSAR Classic", 1.0), m("ISO 26262", 1.0), m("MATLAB/Simulink", 1.0)]
    r = score_fit(matched, [], REQS)
    assert r["score"] == 100
    assert r["band"] == "STRONG"


def test_soft_gap_still_strong():
    """Missing a *tool* shouldn't stop a well-matched application."""
    matched = [m("AUTOSAR Classic", 0.95), m("ISO 26262", 0.9), m("MATLAB/Simulink", 0.95)]
    r = score_fit(matched, ["Jenkins"], REQS)
    assert r["score"] == 70
    assert r["band"] == "STRONG"
    assert r["hard_gaps"] == []


def test_hard_gap_caps_a_strong_score_at_stretch():
    """High coverage but a missing certification -> gated down, and told why."""
    matched = [m("AUTOSAR Classic", 0.95), m("ISO 26262", 0.9), m("MATLAB/Simulink", 0.95)]
    r = score_fit(matched, ["DO-254"], REQS)
    assert r["score"] == 70                # score itself is unchanged...
    assert r["band"] == "STRETCH"          # ...but the verdict is gated
    assert r["hard_gaps"] == ["DO-254"]
    assert "DO-254" in r["reason"]


def test_hard_gap_never_promotes_a_weak_fit():
    r = score_fit([m("AUTOSAR Classic", 0.3)], ["DO-254", "a", "b", "c"], REQS)
    assert r["band"] == "SKIP"


def test_weak_coverage_is_skip():
    r = score_fit([m("x", 0.3)], ["a", "b", "c", "d"], REQS)
    assert r["score"] < 40
    assert r["band"] == "SKIP"


def test_low_confidence_matches_score_below_high_confidence():
    """Same coverage, different certainty -> different score."""
    hi = score_fit([m("a", 0.9), m("b", 0.9)], ["c"], REQS)
    lo = score_fit([m("a", 0.4), m("b", 0.4)], ["c"], REQS)
    assert hi["score"] > lo["score"]


@pytest.mark.parametrize("conf,expected_band", [
    (1.00, "STRONG"),    # 100%
    (0.56, "STRONG"),    # 56% — just over the 55 line
    (0.54, "STRETCH"),   # 54% — just under
    (0.36, "STRETCH"),   # 36% — lower edge of stretch
    (0.34, "SKIP"),      # 34% — just under
])
def test_band_edges(conf, expected_band):
    """One matched requirement out of one, at varying confidence."""
    assert score_fit([m("a", conf)], [], REQS)["band"] == expected_band


def test_unknown_category_gap_is_not_hard():
    """A gap the LLM didn't categorise must not be treated as a blocker."""
    matched = [m("a", 0.9), m("b", 0.9), m("c", 0.9)]
    r = score_fit(matched, ["something not in requirements"], REQS)
    assert r["hard_gaps"] == []
    assert r["band"] == "STRONG"
