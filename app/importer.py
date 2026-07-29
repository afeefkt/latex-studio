"""Importer: parse work history text into facts.yaml structure."""

import re

from app.paths import WORKSPACE

# Patterns for extracting role information from text
ROLE_HEADER_RE = re.compile(
    r"^(?P<title>.+?)\s+(?:at|@|with)\s+(?P<org>.+?)(?:,\s*(?P<location>[^\(]+))?"
    r"\s*(?:\((?P<dates>[^\)]+)\)|(?P<open_start>[A-Z][a-z]{2}\s*\d{4})\s*[-–—]\s*"
    r"(?P<open_end>[A-Z][a-z]*\s*\d{0,4}))",
    re.IGNORECASE,
)

BULLET_RE = re.compile(r"^\s*[-•*]\s+(?P<text>.+)$", re.IGNORECASE)

TOOLS_RE = re.compile(
    r"(?:Tools|Technologies|Stack)(?:\s*used)?\s*:?\s*(?P<tools>.+)$",
    re.IGNORECASE,
)

DATE_RANGE_RE = re.compile(
    r"(?P<start>[A-Z][a-z]{2,}\s*\d{4})\s*[-–—]\s*(?P<end>(?:[A-Z][a-z]{2,}\s*\d{4}|Present|Now|Current))",
    re.IGNORECASE,
)


def _parse_date_range(dates_str: str) -> tuple[str, str]:
    m = DATE_RANGE_RE.search(dates_str)
    if m:
        return m.group("start").strip(), m.group("end").strip()
    parts = [p.strip() for p in dates_str.replace("-", "–").split("–")]
    if len(parts) >= 2:
        return parts[0], parts[1]
    return dates_str, "Present"


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")


def parse_work_history(text: str) -> dict:
    """Parse a work history text into a structured facts format."""
    lines = text.strip().split("\n")

    roles = []
    current_role = None
    current_bullets = []
    current_tools = []
    in_role = False
    other_lines = []

    for line in lines:
        line = line.strip()
        if not line:
            if current_role and current_bullets:
                current_role["bullets"] = current_bullets
                current_role["tools"] = current_tools if current_tools else None
                roles.append(current_role)
                current_role = None
                current_bullets = []
                current_tools = []
                in_role = False
            continue

        # Try to match a role header
        role_match = ROLE_HEADER_RE.match(line)
        if role_match and not in_role:
            # Save previous role if any
            if current_role and current_bullets:
                current_role["bullets"] = current_bullets
                current_role["tools"] = current_tools if current_tools else None
                roles.append(current_role)
                current_bullets = []
                current_tools = []

            title = role_match.group("title").strip()
            org = role_match.group("org").strip()
            location = role_match.group("location").strip() if role_match.group("location") else ""
            dates = role_match.group("dates") or f"{role_match.group('open_start')}-{role_match.group('open_end')}"
            start, end = _parse_date_range(dates) if dates else ("", "")

            role_id = _slugify(org.split("(")[0].strip())
            current_role = {
                "id": role_id,
                "title": title,
                "org": org,
                "location": location,
                "start": start,
                "end": end,
                "duration": "",
                "bullets": [],
                "tools": [],
            }
            in_role = True
            continue

        if in_role:
            # Check for bullet points
            bullet_match = BULLET_RE.match(line)
            if bullet_match:
                text = bullet_match.group("text").strip()
                bid = f"{current_role['id']}_{len(current_bullets)+1}"
                current_bullets.append({
                    "id": bid,
                    "text": text,
                    "tags": [],
                })
                continue

            # Check for tools line
            tools_match = TOOLS_RE.match(line)
            if tools_match:
                tools_str = tools_match.group("tools")
                current_tools = [t.strip() for t in tools_str.split(",")]
                continue

            # If we have bullets already, this might be continuation of previous bullet
            if current_bullets and line:
                current_bullets[-1]["text"] += " " + line
        else:
            other_lines.append(line)

    # Don't forget the last role
    if current_role and current_bullets:
        current_role["bullets"] = current_bullets
        current_role["tools"] = current_tools if current_tools else None
        roles.append(current_role)

    # Try to extract identity info from remaining lines
    name = ""
    email = ""
    phone = ""
    location = ""
    for line in other_lines:
        if "@" in line and "." in line:
            email = line.strip()
        elif re.match(r"^[\+]?[\d\s\-\(\)]{7,}$", line):
            phone = line.strip()
        elif not name and len(line) < 80 and not any(c in line for c in "•-@"):
            name = line.strip()
        elif re.search(r"\d{5}\s+\w+", line):
            location = line.strip()

    identity = {}
    if name:
        identity["name"] = name
    if email:
        identity["email"] = email
    if phone:
        identity["phone"] = phone
    if location:
        identity["address"] = location
        identity["location"] = location

    result = {}
    if identity:
        result["identity"] = identity
    if roles:
        result["roles"] = roles

    return result


def import_to_facts(text: str, existing_facts: dict | None = None) -> dict:
    """
    Parse work history text and merge into existing facts.yaml structure.
    If existing_facts is provided, merges new roles/identity into it.
    Returns the merged facts dict.
    """
    parsed = parse_work_history(text)
    base = existing_facts or {}

    if parsed.get("identity"):
        base["identity"] = {**base.get("identity", {}), **parsed["identity"]}

    if parsed.get("roles"):
        existing_roles = base.get("roles", [])
        existing_ids = {r.get("id", "") for r in existing_roles}
        for role in parsed["roles"]:
            if role["id"] not in existing_ids:
                existing_roles.append(role)
                existing_ids.add(role["id"])
        base["roles"] = existing_roles

    return base
