# ── CV translation: extract → translate → substitute ──
#
# The letter is one prose blob, so /translate can round-trip it as free text.
# A CV cannot: it is a *structure* of short strings, and a free-text translation
# would destroy the mapping between a bullet and the role it belongs under.
#
# So the CV is translated as a flat {key: string} map. The key scheme is stable
# and content-derived (bullet ids, role org+start) rather than positional, so the
# same key addresses the same string in both `facts.roles` and the tailored
# `role_groups` view — the two structures templates may render from.
#
# What is deliberately NOT collected: names, emails, phones, URLs, company names,
# institution names, city names, tool lists and skill names. Those are proper
# nouns; sending them to a translator can only corrupt them. They are the
# fact-bank's identity anchors and must survive verbatim.

import copy
import re

# Values longer than this are almost certainly not a CV field — refuse to ship
# them to the translator rather than silently truncating downstream.
_MAX_VALUE_LEN = 2000


def _rkey(org: str, start: str) -> str:
    """Stable key for a role, derived from employer + start date.

    Positional keys would break the moment `role_groups` skips a role that
    `facts.roles` keeps (a role with no bullets), silently shifting every
    later role's translation onto the wrong entry.
    """
    base = re.sub(r"[^a-z0-9]+", "", f"{org}{start}".lower())[:24]
    return f"role.{base}"


def collect_cv_strings(cv_vars: dict) -> dict[str, str]:
    """Flatten every translatable CV string into {key: english_text}."""
    out: dict[str, str] = {}

    def put(key: str, value) -> None:
        text = ("" if value is None else str(value)).strip()
        if text and len(text) <= _MAX_VALUE_LEN:
            out.setdefault(key, text)

    facts = cv_vars.get("facts") or {}
    ident = facts.get("identity") or {}
    put("about", ident.get("about"))
    put("jobtitle", ident.get("title"))
    put("nationality", ident.get("nationality"))
    put("work_auth", ident.get("work_authorisation"))

    # Both role views, same keys — whichever the template renders from, it matches.
    for role in facts.get("roles") or []:
        k = _rkey(role.get("org", ""), role.get("start", ""))
        put(f"{k}.title", role.get("title"))
        put(f"{k}.duration", role.get("duration"))
        put(f"{k}.end", role.get("end"))
        for b in role.get("bullets") or []:
            if b.get("id"):
                put(f"bullet.{b['id']}", b.get("text"))

    for rg in cv_vars.get("role_groups") or []:
        k = _rkey(rg.get("org", ""), rg.get("start", ""))
        put(f"{k}.title", rg.get("role_title"))
        put(f"{k}.duration", rg.get("duration"))
        put(f"{k}.end", rg.get("end"))
        for b in rg.get("bullets") or []:
            if b.get("id"):
                put(f"bullet.{b['id']}", b.get("text"))

    for i, edu in enumerate(facts.get("education") or []):
        if isinstance(edu, dict):
            put(f"edu.{i}.degree", edu.get("degree"))
            put(f"edu.{i}.focus", edu.get("focus"))

    for i, aw in enumerate(facts.get("awards") or []):
        if isinstance(aw, dict):
            put(f"award.{i}.title", aw.get("title"))
            put(f"award.{i}.description", aw.get("description"))

    for i, hobby in enumerate(facts.get("hobbies") or []):
        put(f"hobby.{i}", hobby)

    # Language proficiency labels ("Professional", "B1 (BAMF Certified)").
    # The language *names* are translated too — a German CV says "Englisch".
    for i, entry in enumerate(facts.get("languages") or []):
        if isinstance(entry, dict):
            put(f"lang.{i}.name", entry.get("lang"))
            put(f"lang.{i}.level", entry.get("level"))
    for i, row in enumerate(cv_vars.get("language_rows") or []):
        put(f"lang.{i}.name", row.get("name"))
        put(f"lang.{i}.level", row.get("level"))

    return out


def apply_cv_strings(cv_vars: dict, tmap: dict) -> dict:
    """Substitute translated strings back into a *copy* of the CV variables.

    `facts` is deep-copied first: it is the dict `load_facts()` returned and the
    letter spec in the same request renders from it too. Mutating it in place
    would translate the letter's fact references as a side effect.

    Any key the translator dropped falls back to the English original, so a
    partial response degrades to a partly-English CV rather than a blank field.
    """
    if not tmap:
        return cv_vars

    out = dict(cv_vars)
    out["facts"] = copy.deepcopy(cv_vars.get("facts") or {})

    def get(key: str, current):
        value = tmap.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return current

    facts = out["facts"]
    ident = facts.get("identity")
    if isinstance(ident, dict):
        ident["about"] = get("about", ident.get("about"))
        ident["title"] = get("jobtitle", ident.get("title"))
        ident["nationality"] = get("nationality", ident.get("nationality"))
        ident["work_authorisation"] = get("work_auth", ident.get("work_authorisation"))

    for role in facts.get("roles") or []:
        k = _rkey(role.get("org", ""), role.get("start", ""))
        role["title"] = get(f"{k}.title", role.get("title"))
        role["duration"] = get(f"{k}.duration", role.get("duration"))
        role["end"] = get(f"{k}.end", role.get("end"))
        for b in role.get("bullets") or []:
            if b.get("id"):
                b["text"] = get(f"bullet.{b['id']}", b.get("text"))

    # role_groups and language_rows are rebuilt on every _cv_vars call, so they
    # are already private to this request and safe to mutate in place.
    for rg in out.get("role_groups") or []:
        k = _rkey(rg.get("org", ""), rg.get("start", ""))
        rg["role_title"] = get(f"{k}.title", rg.get("role_title"))
        rg["duration"] = get(f"{k}.duration", rg.get("duration"))
        rg["end"] = get(f"{k}.end", rg.get("end"))
        # `dates` is derived, not stored — rebuild it so a translated "Present"
        # ("Heute") reaches the templates that render the range instead of end.
        rg["dates"] = f"{rg.get('start', '')} – {rg.get('end', '')}"
        for b in rg.get("bullets") or []:
            if b.get("id"):
                b["text"] = get(f"bullet.{b['id']}", b.get("text"))

    for i, edu in enumerate(facts.get("education") or []):
        if isinstance(edu, dict):
            edu["degree"] = get(f"edu.{i}.degree", edu.get("degree"))
            edu["focus"] = get(f"edu.{i}.focus", edu.get("focus"))

    for i, aw in enumerate(facts.get("awards") or []):
        if isinstance(aw, dict):
            aw["title"] = get(f"award.{i}.title", aw.get("title"))
            aw["description"] = get(f"award.{i}.description", aw.get("description"))

    hobbies = facts.get("hobbies")
    if isinstance(hobbies, list):
        for i, hobby in enumerate(hobbies):
            hobbies[i] = get(f"hobby.{i}", hobby)

    for i, entry in enumerate(facts.get("languages") or []):
        if isinstance(entry, dict):
            entry["lang"] = get(f"lang.{i}.name", entry.get("lang"))
            entry["level"] = get(f"lang.{i}.level", entry.get("level"))

    for i, row in enumerate(out.get("language_rows") or []):
        row["name"] = get(f"lang.{i}.name", row.get("name"))
        row["level"] = get(f"lang.{i}.level", row.get("level"))

    return out
