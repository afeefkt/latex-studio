# ── Phase 1: Translation preservation check ──

import re

from app.guard.factbank import FactBank
from app.guard.validator import NUMBER_RE

# Separator-normalised digit multisets — German writes 3,5 for 3.5 and 1.000
# for 1,000, so literal string comparison false-errors on a correct translation.
_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")
_SEP_RE = re.compile(r"[.,]")


def _normalised_numbers(text: str) -> list[str]:
    """Extract numbers, strip thousand/decimal separators, sort.
    '3.5 years' and '3,5 Jahre' both normalise to ['35'].
    """
    nums = []
    for m in _NUM_RE.finditer(text):
        raw = m.group(0)
        nums.append(_SEP_RE.sub("", raw))
    nums.sort()
    return nums


def check_translation(
    original: str,
    translated: str,
    facts: FactBank,
) -> dict:
    """Compare original and translated text for preservation.

    Returns {"errors": [...], "warnings": [...]} where each entry is
    {"rule": int, "message": str, "detail": str}.

    Asymmetric severity: new numbers → error (translator invented a figure);
    missing numbers → warning (model spelled it out, '8 years' → 'acht Jahre').
    Entities from the fact bank that vanish are a warning.
    """
    errors: list[dict] = []
    warnings: list[dict] = []

    # ── Numbers ──
    orig_nums = set(_normalised_numbers(original))
    trans_nums = set(_normalised_numbers(translated))

    new_nums = trans_nums - orig_nums
    missing_nums = orig_nums - trans_nums

    for n in new_nums:
        errors.append({
            "rule": "translate_numbers",
            "severity": "error",
            "message": f"New number introduced in translation: '{n}'",
            "detail": "The translator may have invented a figure. Verify manually.",
        })
    for n in missing_nums:
        warnings.append({
            "rule": "translate_numbers",
            "severity": "warning",
            "message": f"Number absent from translation: '{n}'",
            "detail": "The model may have spelled it out (acceptable). Verify manually.",
        })

    # ── Proper-noun entities (from fact bank) ──
    # Scan facts.all_entities directly rather than via ENTITY_RE: the regex only
    # matches space-separated title-case runs, so "MATLAB/Simulink" and other
    # punctuated entities never match.
    for ent in facts.all_entities:
        if len(ent) <= 2:
            continue
        if ent in original and ent not in translated:
            warnings.append({
                "rule": "translate_entities",
                "severity": "warning",
                "message": f"Fact-bank entity missing from translation: '{ent}'",
                "detail": "A known proper noun was dropped or altered.",
            })

    return {"errors": errors, "warnings": warnings}
