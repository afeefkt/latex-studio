# ── Phase 4: Guard tests — 14 adversarial test cases ──

from app.guard.models import MatchedRequirement, TailorResponse
from app.guard.validator import validate_tailor_response


# ═══════════════════════════════════════════════════════════════════════════════
# Rule 1: JSON schema validation
# ═══════════════════════════════════════════════════════════════════════════════

def test_invalid_json_not_json(sample_facts, sample_job_ad):
    """Malformed JSON string → Rule 1 error."""
    result = validate_tailor_response("not valid json", sample_job_ad, sample_facts)
    assert not result.passed
    assert any(e.rule == 1 for e in result.errors)


def test_invalid_json_missing_field(sample_facts, sample_job_ad):
    """Valid JSON but missing required field → Rule 1 error."""
    bad = {"selected_bullet_ids": ["koosys_foc"]}  # missing required fields
    result = validate_tailor_response(bad, sample_job_ad, sample_facts)
    assert not result.passed
    assert any(e.rule == 1 for e in result.errors)


# ═══════════════════════════════════════════════════════════════════════════════
# Rule 2: fact_id existence
# ═══════════════════════════════════════════════════════════════════════════════

def test_invented_fact_id(sample_facts, sample_job_ad):
    """Mandated test #1: invented fact_id → Rule 2 error."""
    bad = TailorResponse(
        matched_requirements=[
            MatchedRequirement(jd_phrase="test", fact_ids=["fake_bullet_99"], confidence=0.9),
        ],
        selected_bullet_ids=["koosys_foc"],
        focus_phrase="MATLAB/Simulink",
        hook_key="exact_match",
    )
    result = validate_tailor_response(bad, sample_job_ad, sample_facts)
    assert not result.passed
    assert any("fake_bullet_99" in e.message for e in result.errors)


def test_invented_selected_bullet_id(sample_facts, sample_job_ad):
    """selected_bullet_ids contains non-existent ID → Rule 2 error."""
    bad = TailorResponse(
        matched_requirements=[
            MatchedRequirement(jd_phrase="test", fact_ids=["koosys_foc"], confidence=0.9),
        ],
        selected_bullet_ids=["fake_id_xyz"],
        focus_phrase="MATLAB/Simulink",
        hook_key="exact_match",
    )
    result = validate_tailor_response(bad, sample_job_ad, sample_facts)
    assert not result.passed
    assert any("fake_id_xyz" in e.message for e in result.errors)


# ═══════════════════════════════════════════════════════════════════════════════
# Rule 3: focus_phrase in job ad
# ═══════════════════════════════════════════════════════════════════════════════

def test_focus_phrase_not_in_jd(sample_facts, sample_job_ad):
    """Mandated test #5: focus_phrase not in JD → Rule 3 error."""
    bad = TailorResponse(
        matched_requirements=[
            MatchedRequirement(jd_phrase="test", fact_ids=["koosys_foc"], confidence=0.9),
        ],
        selected_bullet_ids=["koosys_foc"],
        focus_phrase="quantum computing",
        hook_key="exact_match",
    )
    result = validate_tailor_response(bad, sample_job_ad, sample_facts)
    assert not result.passed
    assert any(e.rule == 3 for e in result.errors)


def test_focus_phrase_whitespace_normalised(sample_facts, sample_job_ad):
    """focus_phrase with extra whitespace → should still match (Rule 3 passes)."""
    good = TailorResponse(
        matched_requirements=[
            MatchedRequirement(jd_phrase="test", fact_ids=["koosys_foc"], confidence=0.9),
        ],
        selected_bullet_ids=["koosys_foc"],
        focus_phrase="   model-based    development   using  MATLAB/Simulink   ",
        hook_key="exact_match",
    )
    result = validate_tailor_response(good, sample_job_ad, sample_facts)
    assert result.passed


# ═══════════════════════════════════════════════════════════════════════════════
# Rule 4: hook_key in enum
# ═══════════════════════════════════════════════════════════════════════════════

def test_bad_hook_key(sample_facts, sample_job_ad):
    """Invalid hook_key → Rule 4 error."""
    bad = TailorResponse(
        matched_requirements=[
            MatchedRequirement(jd_phrase="test", fact_ids=["koosys_foc"], confidence=0.9),
        ],
        selected_bullet_ids=["koosys_foc"],
        focus_phrase="MATLAB/Simulink",
        hook_key="awesome_candidate_ever",
    )
    result = validate_tailor_response(bad, sample_job_ad, sample_facts)
    assert not result.passed
    assert any(e.rule == 4 for e in result.errors)


# ═══════════════════════════════════════════════════════════════════════════════
# Rule 5: banned claims
# ═══════════════════════════════════════════════════════════════════════════════

def test_claims_istqb(sample_facts, sample_job_ad):
    """Mandated test #2: claims ISTQB → Rule 5 error."""
    letter = "I am an ISTQB certified tester with extensive experience."
    result = validate_tailor_response(
        {"selected_bullet_ids": [], "matched_requirements": [],
         "focus_phrase": "test", "hook_key": "exact_match"},
        sample_job_ad, sample_facts, assembled_text=letter,
    )
    assert not result.passed
    assert any(e.rule == 5 for e in result.errors)


def test_multiple_banned_claims(sample_facts, sample_job_ad):
    """Letter contains multiple banned claims → Rule 5 catches all."""
    letter = "I hold a PhD and have security clearance. I am DO-254 certified."
    result = validate_tailor_response(
        {"selected_bullet_ids": [], "matched_requirements": [],
         "focus_phrase": "test", "hook_key": "exact_match"},
        sample_job_ad, sample_facts, assembled_text=letter,
    )
    assert not result.passed
    rule5_errors = [e for e in result.errors if e.rule == 5]
    assert len(rule5_errors) >= 3  # PhD, security clearance, DO-254


# ═══════════════════════════════════════════════════════════════════════════════
# Rule 6: numbers from facts
# ═══════════════════════════════════════════════════════════════════════════════

def test_false_experience_years(sample_facts, sample_job_ad):
    """Mandated test #3: '7 years avionics' → Rule 6 error."""
    letter = "I have 7 years of avionics development experience."
    result = validate_tailor_response(
        {"selected_bullet_ids": [], "matched_requirements": [],
         "focus_phrase": "test", "hook_key": "exact_match"},
        sample_job_ad, sample_facts, assembled_text=letter,
    )
    assert not result.passed
    assert any(e.rule == 6 for e in result.errors)


def test_false_percentage(sample_facts, sample_job_ad):
    """Mandated test #6: 'reduced test time by 65%' → Rule 6 error (65 not in facts)."""
    letter = "I reduced test execution time by 65% through automation."
    result = validate_tailor_response(
        {"selected_bullet_ids": [], "matched_requirements": [],
         "focus_phrase": "test", "hook_key": "exact_match"},
        sample_job_ad, sample_facts, assembled_text=letter,
    )
    assert not result.passed
    assert any(e.rule == 6 for e in result.errors)


# ═══════════════════════════════════════════════════════════════════════════════
# Rule 7: entity validation
# ═══════════════════════════════════════════════════════════════════════════════

def test_invented_tool(sample_facts, sample_job_ad):
    """Mandated test #4: 'developed in VxWorks' → Rule 7 warning."""
    letter = "I developed real-time firmware in VxWorks for safety-critical systems."
    result = validate_tailor_response(
        {"selected_bullet_ids": [], "matched_requirements": [],
         "focus_phrase": "test", "hook_key": "exact_match"},
        sample_job_ad, sample_facts, assembled_text=letter,
    )
    assert any(e.rule == 7 for e in result.warnings)


def test_entity_in_jd_allowed(sample_facts, sample_job_ad):
    """Entity in JD but not facts → Rule 7 passes (allowlisted via JD)."""
    letter = "I have experience with Field Weakening motor control techniques."
    result = validate_tailor_response(
        {"selected_bullet_ids": [], "matched_requirements": [],
         "focus_phrase": "MATLAB/Simulink", "hook_key": "exact_match"},
        sample_job_ad, sample_facts, assembled_text=letter,
    )
    # "Field Weakening" appears in the JD → should not warn
    # Note: depends on entity extraction regex matching "Field Weakening"
    rule7_warnings = [w for w in result.warnings if w.rule == 7]
    # If the entity is in JD, no warnings should fire for it
    fw_warning = [w for w in rule7_warnings if "Field" in w.detail]
    assert len(fw_warning) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Rule 8: text length
# ═══════════════════════════════════════════════════════════════════════════════

def test_letter_too_short(sample_facts, sample_job_ad):
    """Very short letter → Rule 8 warning."""
    letter = "I am applying for this role. Thank you."
    result = validate_tailor_response(
        {"selected_bullet_ids": [], "matched_requirements": [],
         "focus_phrase": "test", "hook_key": "exact_match"},
        sample_job_ad, sample_facts, assembled_text=letter,
    )
    assert any(e.rule == 8 for e in result.warnings)


# ═══════════════════════════════════════════════════════════════════════════════
# Rule 9: certifications
# ═══════════════════════════════════════════════════════════════════════════════

def test_false_degree(sample_facts, sample_job_ad):
    """Claims 'certified in DO-178C' → Rule 9 error (not in certifications_held)."""
    letter = "I am certified in DO-178C software development standards."
    result = validate_tailor_response(
        {"selected_bullet_ids": [], "matched_requirements": [],
         "focus_phrase": "test", "hook_key": "exact_match"},
        sample_job_ad, sample_facts, assembled_text=letter,
    )
    assert not result.passed
    assert any(e.rule == 9 for e in result.errors)


def test_claimable_certification_allowed(sample_facts, sample_job_ad):
    """Uses claimable_as phrasing → Rule 9 passes."""
    letter = "I am familiar with the objectives of DO-178C through self-study."
    result = validate_tailor_response(
        {"selected_bullet_ids": [], "matched_requirements": [],
         "focus_phrase": "test", "hook_key": "exact_match"},
        sample_job_ad, sample_facts, assembled_text=letter,
    )
    # Should pass — claimable_as "familiar with the objectives of DO-178C" is allowed
    assert not any(e.rule == 9 for e in result.errors)


# ═══════════════════════════════════════════════════════════════════════════════
# Combined and edge-case tests
# ═══════════════════════════════════════════════════════════════════════════════

def test_valid_response_passes(sample_facts, sample_job_ad, valid_response, valid_letter_text):
    """Clean response passes all 9 rules."""
    result = validate_tailor_response(valid_response, sample_job_ad, sample_facts, valid_letter_text)
    assert result.passed
    assert len(result.errors) == 0
    # May have warnings (Rule 7/8) — that's fine, warnings don't block


def test_combined_failures(sample_facts, sample_job_ad):
    """Multiple rules violated at once → all errors reported."""
    bad = TailorResponse(
        matched_requirements=[
            MatchedRequirement(jd_phrase="test", fact_ids=["fake_id_1"], confidence=0.9),
        ],
        selected_bullet_ids=["fake_id_2"],
        focus_phrase="not in job ad",
        hook_key="invalid_hook_key",
    )
    letter = "I am ISTQB certified with 15 years of experience. I hold a security clearance."
    result = validate_tailor_response(bad, sample_job_ad, sample_facts, assembled_text=letter)

    # Multiple rules should have fired
    violated_rules = {e.rule for e in result.errors}
    assert 2 in violated_rules  # fake fact_ids
    assert 3 in violated_rules  # focus_phrase not in JD
    assert 4 in violated_rules  # bad hook_key
    assert 5 in violated_rules  # banned claims


def test_rule_2_double_counted_ids(sample_facts, sample_job_ad):
    """Same fake ID in both matched_requirements and selected → reported once per occurrence."""
    bad = TailorResponse(
        matched_requirements=[
            MatchedRequirement(jd_phrase="test", fact_ids=["nonexistent_id"], confidence=0.9),
            MatchedRequirement(jd_phrase="test2", fact_ids=["nonexistent_id"], confidence=0.8),
        ],
        selected_bullet_ids=["nonexistent_id"],
        focus_phrase="MATLAB/Simulink",
        hook_key="exact_match",
    )
    result = validate_tailor_response(bad, sample_job_ad, sample_facts)
    # Should report each occurrence
    rule2_errors = [e for e in result.errors if e.rule == 2]
    assert len(rule2_errors) >= 2


def test_rule_6_known_numbers_pass(sample_facts, sample_job_ad, valid_letter_text):
    """Letter with only known numbers → Rule 6 passes."""
    result = validate_tailor_response(
        {"selected_bullet_ids": [], "matched_requirements": [],
         "focus_phrase": "MATLAB/Simulink", "hook_key": "exact_match"},
        sample_job_ad, sample_facts, assembled_text=valid_letter_text,
    )
    rule6_errors = [e for e in result.errors if e.rule == 6]
    assert len(rule6_errors) == 0
