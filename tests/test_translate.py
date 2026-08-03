# ── Translation preservation tests ──
#
# The DO-178C test is the anchor case that justifies the entire design.
# Write it first, as the plan mandates.

from app.guard.models import FactBank
from app.translate import check_translation


def _facts() -> FactBank:
    return FactBank(
        raw={},
        all_fact_ids=set(),
        all_numbers=set(),
        all_entities={"DO-178C", "ISO 26262", "MATLAB/Simulink"},
        all_skills=set(),
        banned_claims=[
            "do-178c certified", "do-178c-zertifiziert",
            "security clearance", "phd",
        ],
        certifications_held=[],
        certifications_in_progress=[
            {"name": "DO-178C", "status": "self-study",
             "claimable_as": "familiar with the objectives of DO-178C"},
        ],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# DO-178C hedge case — the plan's justification test
# ═══════════════════════════════════════════════════════════════════════════════

def test_do178c_hedge_is_not_a_certification():
    """Translating 'familiar with DO-178C' → 'DO-178C-zertifiziert'
    must be caught at the write gate.

    check_translation only verifies number/entity preservation — DO-178C is still
    present in 'DO-178C-zertifiziert' so the entity check passes.  The hedge
    collapse (hedge word → certification suffix) is caught by validate_write_gate
    rule 5, because 'do-178c-zertifiziert' is listed in banned_claims.
    """
    from app.guard.validator import validate_write_gate
    translated = "Ich bin DO-178C-zertifiziert."
    gate = validate_write_gate(translated, _facts())
    assert not gate.passed
    assert any(e.rule == 5 for e in gate.errors)


# ═══════════════════════════════════════════════════════════════════════════════
# Identical text
# ═══════════════════════════════════════════════════════════════════════════════

def test_identical_text_no_errors():
    """Translating something identical should produce no errors."""
    text = "I have 8 years of experience with MATLAB/Simulink."
    result = check_translation(text, text, _facts())
    assert len(result["errors"]) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Number preservation
# ═══════════════════════════════════════════════════════════════════════════════

def test_new_number_is_error():
    """A figure not in the original → error."""
    original = "I have 3 years of experience."
    translated = "Ich habe 5 Jahre Erfahrung."
    result = check_translation(original, translated, _facts())
    assert len(result["errors"]) >= 1
    assert any("5" in e["message"] for e in result["errors"])


def test_spelled_out_number_is_warning():
    """'8 years' → 'acht Jahre' — number missing but spelled out → warning."""
    original = "I have 8 years of experience."
    translated = "Ich habe acht Jahre Erfahrung."
    result = check_translation(original, translated, _facts())
    # Missing numbers are warnings, not errors
    nums_errors = [e for e in result["errors"] if "number" in e.get("rule", "")]
    nums_warnings = [w for w in result["warnings"] if "number" in w.get("rule", "")]
    assert len(nums_errors) == 0
    assert len(nums_warnings) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# Entity preservation
# ═══════════════════════════════════════════════════════════════════════════════

def test_fact_bank_entity_missing_is_warning():
    """A known entity vanishing from the translation → warning."""
    original = "I worked with MATLAB/Simulink at KooSys GmbH."
    translated = "Ich arbeitete mit einem Modellierungswerkzeug."
    result = check_translation(original, translated, _facts())
    entity_warnings = [w for w in result["warnings"] if "entities" in w.get("rule", "")]
    assert len(entity_warnings) >= 1


def test_decimal_separator_preserves_equivalence():
    """3,5 Jahre and 3.5 years should be considered equivalent numbers."""
    original = "I have 3.5 years of experience and rate 4.0."
    translated = "Ich habe 3,5 Jahre Erfahrung und bewerte 4,0."
    result = check_translation(original, translated, _facts())
    # Separator-normalised: 35 == 35, 40 == 40 → no new or missing
    nums_errors = [e for e in result["errors"] if "number" in e.get("rule", "")]
    assert len(nums_errors) == 0
