# ── P7: Application tracker — CSV logger ──

import csv
from datetime import datetime, timezone

from app.paths import WORKSPACE
APPS_CSV = WORKSPACE / "applications.csv"

COLUMNS = [
    "company_name", "role_title", "location", "date_generated",
    "status", "applied_date", "response_date",
    "letter_path", "cv_path",
    "matched_count", "unmatched_count", "unmatched_list", "notes",
]


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
) -> None:
    """Append a new application row to the CSV."""
    APPS_CSV.parent.mkdir(parents=True, exist_ok=True)
    exists = APPS_CSV.exists()

    with open(APPS_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not exists:
            writer.writerow(COLUMNS)
        writer.writerow([
            company, role, location,
            datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "generated", "", "",
            letter_path, cv_path,
            matched_count, unmatched_count, unmatched_list, notes,
        ])


def list_applications() -> list[dict]:
    """Read all applications from CSV, newest first."""
    if not APPS_CSV.exists():
        return []
    rows = []
    with open(APPS_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["matched_count"] = int(row.get("matched_count", 0))
            row["unmatched_count"] = int(row.get("unmatched_count", 0))
            rows.append(row)
    rows.reverse()
    return rows


def update_application(index: int, field: str, value: str) -> bool:
    """Update a single field on a specific application row (0-indexed from newest)."""
    if not APPS_CSV.exists():
        return False
    rows = list_applications()
    if index < 0 or index >= len(rows):
        return False
    if field not in COLUMNS:
        return False
    rows[index][field] = value

    with open(APPS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for row in reversed(rows):
            writer.writerow({col: row.get(col, "") for col in COLUMNS})
    return True


def update_latest_cv(cv_path: str) -> bool:
    """Set cv_path on the most recent application."""
    rows = list_applications()
    if not rows:
        return False
    rows[0]["cv_path"] = cv_path

    with open(APPS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for row in reversed(rows):
            writer.writerow({col: row.get(col, "") for col in COLUMNS})
    return True
