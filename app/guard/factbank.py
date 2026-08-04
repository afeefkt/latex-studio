# ── Phase 4: FactBank — load + index facts.yaml ──

import re
from pathlib import Path

import yaml

from app.guard.models import FactBank
from app.paths import WORKSPACE
DEFAULT_FACTS_PATH = WORKSPACE / "facts.yaml"


def _extract_fact_ids(raw: dict) -> set[str]:
    ids: set[str] = set()
    for role in raw.get("roles", []):
        if "id" in role:
            ids.add(role["id"])
        for bullet in role.get("bullets", []):
            if "id" in bullet:
                ids.add(bullet["id"])
    return ids


def _extract_numbers(raw: dict) -> set[str]:
    """Extract every number, year, duration from facts.yaml text fields."""
    # Walk all string values and extract digit sequences + units
    numbers: set[str] = set()

    def _walk(obj):
        if isinstance(obj, str):
            for m in re.finditer(r"\d+(?:\.\d+)?(?:\s*(?:%|months?|years?|weeks?))?", obj):
                val = m.group(0).strip()
                if val:
                    numbers.add(val)
            # Extract individual years from ranges like "2011 -- 2015"
            for m in re.finditer(r"\b(19|20)\d{2}\b", obj):
                numbers.add(m.group(0))
        elif isinstance(obj, dict):
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(raw)
    return numbers


def _extract_entities(raw: dict) -> set[str]:
    """Extract capitalised multi-word entities: tools, orgs, standards, locations, degrees."""
    entities: set[str] = set()
    entity_re = re.compile(
        r"[A-Z][a-z]+(?:\s+[A-Z][a-zA-Z]+)+|\b[A-Z]{2,}(?:\s+[A-Z]{2,})+\b|\bISO\s+\d+\b"
    )

    def _walk(obj):
        if isinstance(obj, str):
            for m in entity_re.finditer(obj):
                entities.add(m.group(0))
        elif isinstance(obj, dict):
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    # Walk only key fields: tools, skills, orgs, roles[].title, education
    for role in raw.get("roles", []):
        if isinstance(role.get("org"), str):
            entities.add(role["org"])
        if isinstance(role.get("title"), str):
            for m in entity_re.finditer(role["title"]):
                entities.add(m.group(0))
        if isinstance(role.get("tools"), list):
            for t in role["tools"]:
                if isinstance(t, str):
                    entities.add(t)
    for edu in raw.get("education", []):
        if isinstance(edu.get("institution"), str):
            entities.add(edu["institution"])
        if isinstance(edu.get("degree"), str):
            entities.add(edu["degree"])
    for skill_list in raw.get("skills", {}).values():
        if isinstance(skill_list, list):
            for s in skill_list:
                if isinstance(s, str):
                    entities.add(s)
    if isinstance(raw.get("identity", {}).get("location"), str):
        entities.add(raw["identity"]["location"])

    return entities


def _extract_skills(raw: dict) -> set[str]:
    """Collect all skills from every tier.
    Consumed by: content.py (CV translation — merged with all_entities to build
    the do-not-translate term list so skill names are preserved verbatim).
    Not yet used in any validator rule; reserved for future skill-provenance
    checks (e.g. 'does this claimed skill appear in any bullet?')."""
    skills: set[str] = set()
    for tier in ("expert", "proficient", "familiar"):
        for s in raw.get("skills", {}).get(tier, []):
            if isinstance(s, str):
                skills.add(s)
    return skills


def _normalise_claims(raw: dict) -> list[str]:
    """Lowercase banned claims for case-insensitive matching."""
    return [c.lower().strip() for c in raw.get("banned_claims", [])]


def _extract_certifications(raw: dict) -> tuple[list[str], list[dict]]:
    held = raw.get("certifications_held", [])
    in_progress = raw.get("certifications_in_progress", [])
    return list(held) if held else [], list(in_progress) if in_progress else []


def load_factbank(path: Path | None = None) -> FactBank:
    p = path or DEFAULT_FACTS_PATH
    if not p.exists():
        return FactBank(raw={})

    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    certs_held, certs_ip = _extract_certifications(raw)

    return FactBank(
        raw=raw,
        all_fact_ids=_extract_fact_ids(raw),
        all_numbers=_extract_numbers(raw),
        all_entities=_extract_entities(raw),
        all_skills=_extract_skills(raw),
        banned_claims=_normalise_claims(raw),
        certifications_held=certs_held,
        certifications_in_progress=certs_ip,
    )
