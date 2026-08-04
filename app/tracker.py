# ── P7: Application tracker — CSV logger ──

import csv
import os
from datetime import datetime, timezone

from app.paths import WORKSPACE
APPS_CSV = WORKSPACE / "applications.csv"

COLUMNS = [
    "company_name", "role_title", "location", "date_generated",
    "status", "applied_date", "response_date",
    "letter_path", "cv_path",
    "matched_count", "unmatched_count", "unmatched_list", "notes",
]

NEW_COLUMNS = ["language", "cv_template", "letter_template"]


def _ensure_header() -> None:
    """Idempotent column migration — widens existing CSV without data loss.

    applications.csv already exists with 13-column header on user machines.
    Adding new columns by appending silently corrupts: DictReader shunts the
    14th value into restkey, and the next update_application rewrite drops it.

    Only called when the file already exists and has a header row.
    """
    if not APPS_CSV.exists():
        return

    with open(APPS_CSV, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        lines = list(reader)

    if not lines:
        return

    existing = lines[0]
    needed = [c for c in NEW_COLUMNS if c not in existing]
    if not needed:
        return  # already migrated

    new_header = existing + needed
    new_lines = [new_header]
    for row in lines[1:]:
        padded = row + [""] * len(needed)
        new_lines.append(padded)

    # Write to temp then rename for crash safety
    tmp = APPS_CSV.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(new_lines)
    os.replace(tmp, APPS_CSV)


def log_application(
    company: str = "",
    role: str = "",
    location: str = "",
    letter_path: str = "",
    cv_path: str = "",
    matched_count: int = 0,
    unmatched_count: int = 0,
    unmatched_list: str = "",
    notes: str = "",
    language: str = "",
    cv_template: str = "",
    letter_template: str = "",
) -> None:
    """Append a new application row to the CSV."""
    APPS_CSV.parent.mkdir(parents=True, exist_ok=True)
    exists = APPS_CSV.exists()

    with open(APPS_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not exists:
            writer.writerow(COLUMNS + NEW_COLUMNS)
        writer.writerow([
            company, role, location,
            datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "generated", "", "",
            letter_path, cv_path,
            matched_count, unmatched_count, unmatched_list, notes,
            language, cv_template, letter_template,
        ])


def list_applications() -> list[dict]:
    """Read all applications from CSV, newest first."""
    _ensure_header()
    if not APPS_CSV.exists():
        return []
    rows = []
    with open(APPS_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, restkey="_extra")
        for row in reader:
            row["matched_count"] = int(row.get("matched_count", 0) or 0)
            row["unmatched_count"] = int(row.get("unmatched_count", 0) or 0)
            rows.append(row)
    return list(reversed(rows))


def update_application(index: int, field: str, value: str) -> bool:
    """Update a single field on a specific application row (0-indexed from newest)."""
    if not APPS_CSV.exists():
        return False
    _ensure_header()
    rows = list_applications()
    if index < 0 or index >= len(rows):
        return False
    all_cols = COLUMNS + [c for c in NEW_COLUMNS if c not in COLUMNS]
    if field not in all_cols:
        return False
    rows[index][field] = value

    with open(APPS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_cols, extrasaction="ignore")
        writer.writeheader()
        for row in reversed(rows):
            writer.writerow(row)
    return True


def update_latest_cv(cv_path: str) -> bool:
    """Set cv_path on the most recent application."""
    _ensure_header()
    rows = list_applications()
    if not rows:
        return False
    rows[0]["cv_path"] = cv_path
    all_cols = COLUMNS + [c for c in NEW_COLUMNS if c not in COLUMNS]

    with open(APPS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_cols, extrasaction="ignore")
        writer.writeheader()
        for row in reversed(rows):
            writer.writerow(row)
    return True
