# ── Phase 4: Anti-hallucination validator ──

import re
from pathlib import Path

import yaml
from pydantic import ValidationError as PydanticValidationError

from app.guard.factbank import FactBank, load_factbank
from app.guard.models import TailorResponse, ValidationIssue, ValidationResult

_RULES_PATH = Path(__file__).parent / "rules.yaml"
_rules = yaml.safe_load(_RULES_PATH.read_text(encoding="utf-8")) if _RULES_PATH.exists() else {}

HOOK_KEYS: set[str] = set(_rules.get("hook_keys", []))
LENGTH_TOLERANCE: float = float(_rules.get("length_tolerance", 0.2))
REFERENCE_WORD_COUNT: int = int(_rules.get("reference_word_count", 250))
CERT_PATTERNS: list[re.Pattern] = [
    re.compile(p) for p in _rules.get("certification_patterns", [])
]
NUMBER_RE = re.compile(_rules.get("number_pattern", r"\d+"))
ENTITY_RE = re.compile(_rules.get("entity_pattern", r"[A-Z][a-z]+(?:\s+[A-Z][a-zA-Z]+)+"))


def validate_tailor_response(
    response: dict | str,
    job_ad_text: str,
    facts: FactBank | None = None,
    assembled_text: str | None = None,
) -> ValidationResult:
    """
    Validate an LLM tailoring response against facts.yaml.

    Pass 1 (always): Rules 1-4 — validate JSON structure and basic constraints.
    Pass 2 (optional): Rules 5-9 — validate assembled letter text against facts.

    Args:
        response: JSON dict or string from the LLM.
        job_ad_text: The pasted job ad text.
        facts: Pre-loaded FactBank. Loaded from default path if None.
        assembled_text: Rendered letter body text. If None, Pass 2 is skipped.

    Returns:
        ValidationResult with all errors and warnings accumulated.
    """
    if facts is None:
        facts = load_factbank()

    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    # ── Rule 1: JSON schema validation ──
    parsed = _rule_1_parse(response, errors)
    if parsed is None:
        # Cannot proceed with further Pass 1 rules without valid JSON
        return ValidationResult(passed=False, errors=errors, warnings=warnings)

    # ── Rule 2: All fact_ids exist ──
    _rule_2_fact_ids(parsed, facts, errors)

    # ── Rule 3: focus_phrase is substring of JD ──
    _rule_3_focus_phrase(parsed, job_ad_text, errors)

    # ── Rule 4: hook_key in enum ──
    _rule_4_hook_key(parsed, errors)

    # ── Pass 2: assembled text validation ──
    if assembled_text is not None:
        _rule_5_banned_claims(assembled_text, facts, errors)
        _rule_6_numbers(assembled_text, facts, errors)
        _rule_7_entities(assembled_text, facts, job_ad_text, warnings)
        _rule_8_length(assembled_text, warnings)
        _rule_9_certifications(assembled_text, facts, errors)

    return ValidationResult(
        passed=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


# ── Rule 1: JSON schema ────────────────────────────────────────────────────────

def _rule_1_parse(response: dict | str, errors: list) -> TailorResponse | None:
    if isinstance(response, str):
        import json
        try:
            response = json.loads(response)
        except json.JSONDecodeError as e:
            errors.append(ValidationIssue(
                rule=1, severity="error",
                message="Response is not valid JSON",
                detail=str(e),
            ))
            return None

    try:
        return TailorResponse.model_validate(response)
    except PydanticValidationError as e:
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"])
            errors.append(ValidationIssue(
                rule=1, severity="error",
                message=f"Schema error: {err['msg']}",
                detail=f"Field: {loc}",
            ))
        return None
    except Exception as e:
        errors.append(ValidationIssue(
            rule=1, severity="error",
            message="Failed to parse response",
            detail=str(e),
        ))
        return None


# ── Rule 2: fact_ids exist in facts.yaml ───────────────────────────────────────

def _rule_2_fact_ids(parsed: TailorResponse, facts: FactBank, errors: list) -> None:
    all_ids_in_response: set[str] = set()

    for req in parsed.matched_requirements:
        for fid in req.fact_ids:
            all_ids_in_response.add(fid)
            if fid not in facts.all_fact_ids:
                errors.append(ValidationIssue(
                    rule=2, severity="error",
                    message=f"Invented fact_id: '{fid}'",
                    detail=f"In matched_requirements for phrase '{req.jd_phrase}'",
                ))

    for bid in parsed.selected_bullet_ids:
        all_ids_in_response.add(bid)
        if bid not in facts.all_fact_ids:
            errors.append(ValidationIssue(
                rule=2, severity="error",
                message=f"Invented bullet_id: '{bid}'",
                detail="In selected_bullet_ids",
            ))

    # Verify that selected_bullet_ids are a subset of matched fact_ids
    matched_ids = all_ids_in_response
    for bid in parsed.selected_bullet_ids:
        if bid not in matched_ids and bid in facts.all_fact_ids:
            # This is a logic error: selected but not matched. Not a hallucination.
            pass


# ── Rule 3: focus_phrase appears in job ad ─────────────────────────────────────

def _rule_3_focus_phrase(parsed: TailorResponse, job_ad_text: str, errors: list) -> None:
    phrase = " ".join(parsed.focus_phrase.split()).lower()
    ad = " ".join(job_ad_text.split()).lower()

    if phrase and phrase not in ad:
        errors.append(ValidationIssue(
            rule=3, severity="error",
            message="focus_phrase not found in job ad text",
            detail=f"Phrase: '{parsed.focus_phrase}'",
        ))


# ── Rule 4: hook_key in allowed enum ───────────────────────────────────────────

def _rule_4_hook_key(parsed: TailorResponse, errors: list) -> None:
    if parsed.hook_key not in HOOK_KEYS:
        errors.append(ValidationIssue(
            rule=4, severity="error",
            message=f"Invalid hook_key: '{parsed.hook_key}'",
            detail=f"Must be one of: {', '.join(sorted(HOOK_KEYS))}",
        ))


# ── Rule 5: No banned claims ───────────────────────────────────────────────────

def _rule_5_banned_claims(text: str, facts: FactBank, errors: list) -> None:
    text_lower = text.lower()
    for claim in facts.banned_claims:
        if not claim:
            continue
        # Use word-boundary-aware matching
        pattern = re.compile(r"\b" + re.escape(claim) + r"\b", re.IGNORECASE)
        if pattern.search(text_lower):
            errors.append(ValidationIssue(
                rule=5, severity="error",
                message=f"Banned claim detected: '{claim}'",
                detail="This claim is not in facts.yaml",
            ))


# ── Rule 6: Numbers must appear in facts.yaml ──────────────────────────────────

def _rule_6_numbers(text: str, facts: FactBank, errors: list) -> None:
    # Pre-scan for compound technical terms that embed numbers
    # (e.g. "6-phase", "32-bit", "ISO 26262", "DO-178C")
    # These numbers are part of standard names, not invented figures.
    compound_term = re.compile(
        r'\b(?:ISO|DO|IEC|EN|SAE|MIL|DIN|IEEE)[\s-]+\d+\S*'
        r'|\d+-(?:phase|bit|channel|pole|axis|layer|wire|speed|level|cycle|step|stage|order)\b',
        re.IGNORECASE,
    )
    compound_ranges = [
        (m.start(), m.end())
        for m in compound_term.finditer(text)
    ]

    def _inside_compound(pos: int) -> bool:
        return any(start <= pos < end for start, end in compound_ranges)

    for m in NUMBER_RE.finditer(text):
        num_str = m.group(0).strip()
        if not num_str:
            continue
        # Skip numbers inside standard names or compound technical terms
        if _inside_compound(m.start()):
            continue
        # Skip common formatting patterns
        if num_str in ("", "0", "1", "2", "3", "4", "5"):
            continue
        if num_str[0].isdigit() or (len(num_str) > 1 and num_str[1].isdigit()):
            # Normalise: strip trailing unit (% years months weeks) for comparison
            norm = re.sub(r'\s*(?:%|years?|months?|weeks?)$', '', num_str)
            if num_str not in facts.all_numbers and norm not in facts.all_numbers:
                errors.append(ValidationIssue(
                    rule=6, severity="error",
                    message=f"Number not in facts.yaml: '{num_str}'",
                    detail="All years, durations, and percentages in the letter must appear in facts.yaml",
                ))


# ── Rule 7: Capitalised entities must appear in facts or JD ────────────────────

def _rule_7_entities(text: str, facts: FactBank, job_ad_text: str, warnings: list) -> None:
    # Build JD entity set
    jd_entities: set[str] = set()
    for m in ENTITY_RE.finditer(job_ad_text):
        ent = m.group(0).strip()
        if len(ent) > 2:
            jd_entities.add(ent)

    # Also add all words from JD for lax matching
    jd_words: set[str] = set(job_ad_text.split())

    for m in ENTITY_RE.finditer(text):
        ent = m.group(0).strip()
        if len(ent) <= 2:
            continue
        # Skip common words
        if ent.lower() in ("i am", "i have", "i would", "with", "and", "the", "for", "from"):
            continue
        in_facts = ent in facts.all_entities
        in_jd = ent in jd_entities or ent in jd_words
        if not in_facts and not in_jd:
            warnings.append(ValidationIssue(
                rule=7, severity="warning",
                message=f"Entity not in facts.yaml or job ad: '{ent}'",
                detail="Verify this is a real entity, not a hallucination",
            ))


# ── Rule 8: Text length within ±20% of reference ──────────────────────────────

def _rule_8_length(text: str, warnings: list) -> None:
    word_count = len(text.split())
    low = int(REFERENCE_WORD_COUNT * (1 - LENGTH_TOLERANCE))
    high = int(REFERENCE_WORD_COUNT * (1 + LENGTH_TOLERANCE))

    if word_count < low:
        warnings.append(ValidationIssue(
            rule=8, severity="warning",
            message=f"Letter too short: {word_count} words",
            detail=f"Expected {low}-{high} words",
        ))
    elif word_count > high:
        warnings.append(ValidationIssue(
            rule=8, severity="warning",
            message=f"Letter too long: {word_count} words",
            detail=f"Expected {low}-{high} words",
        ))


# ── Rule 9: No false certifications, clearances, or degrees ────────────────────

def _rule_9_certifications(text: str, facts: FactBank, errors: list) -> None:
    all_certs: set[str] = set()

    for cp in facts.certifications_held:
        all_certs.add(cp.lower().strip())
    for ip in facts.certifications_in_progress:
        if isinstance(ip, dict):
            all_certs.add(ip.get("name", "").lower().strip())
            claimable = ip.get("claimable_as", "")
            if claimable:
                all_certs.add(claimable.lower().strip())

    for pattern in CERT_PATTERNS:
        for m in pattern.finditer(text):
            cert_name = m.group(1).strip().lower() if m.lastindex else ""
            if not cert_name:
                continue
            # Normalise
            cert_name = " ".join(cert_name.split())
            if cert_name in all_certs:
                continue
            # Check if any known cert is a substring
            matched = False
            for known in all_certs:
                if known and (known in cert_name or cert_name in known):
                    matched = True
                    break
            if not matched:
                errors.append(ValidationIssue(
                    rule=9, severity="error",
                    message=f"Unverified certification/degree claim: '{cert_name}'",
                    detail="This certification is not listed in facts.yaml",
                ))
