# ── Tracker CSV tests ──

import csv
import os

import app.tracker as tracker


def test_log_application_creates_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker, "APPS_CSV", tmp_path / "apps.csv")
    # Force a clean state
    monkeypatch.setattr(tracker, "COLUMNS", tracker.COLUMNS)

    tracker.log_application(
        company="Acme Corp", role="Engineer", location="Berlin",
        letter_path="letters/x", cv_path="cv_x",
        matched_count=3, unmatched_count=1,
        unmatched_list="rust", notes="test",
    )
    assert tracker.APPS_CSV.exists()

    rows = tracker.list_applications()
    assert len(rows) == 1
    r = rows[0]
    assert r["company_name"] == "Acme Corp"
    assert r["role_title"] == "Engineer"
    assert r["location"] == "Berlin"
    assert r["matched_count"] == 3
    assert r["unmatched_count"] == 1
    assert r["unmatched_list"] == "rust"
    assert r["notes"] == "test"
    assert r["status"] == "generated"


def test_log_application_writes_new_columns(tmp_path, monkeypatch):
    """With language, cv_template, letter_template filled → new columns written."""
    monkeypatch.setattr(tracker, "APPS_CSV", tmp_path / "apps.csv")
    monkeypatch.setattr(tracker, "COLUMNS", tracker.COLUMNS)

    tracker.log_application(
        company="A", role="B", language="de",
        cv_template="ats-cv", letter_template="scrlttr2-letter",
    )
    rows = tracker.list_applications()
    assert rows[0]["language"] == "de"
    assert rows[0]["cv_template"] == "ats-cv"
    assert rows[0]["letter_template"] == "scrlttr2-letter"


def test_ensure_header_migrates_old_csv(tmp_path, monkeypatch):
    """A 13-column CSV gets widened to 16 columns without data loss."""
    csv_path = tmp_path / "old_apps.csv"
    monkeypatch.setattr(tracker, "APPS_CSV", csv_path)

    old_cols = tracker.COLUMNS  # 13 columns
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(old_cols)
        w.writerow(["acme", "eng", "de", "2024-01-01",
                     "generated", "", "",
                     "letters/x", "cv_x",
                     "3", "1", "gaps", "notes"])

    # Trigger migration via list
    rows = tracker.list_applications()
    assert len(rows) == 1
    assert rows[0]["company_name"] == "acme"
    # New columns exist with empty defaults
    assert rows[0].get("language") == ""
    assert rows[0].get("cv_template") == ""
    assert rows[0].get("letter_template") == ""


def test_ensure_header_idempotent(tmp_path, monkeypatch):
    """Calling _ensure_header twice → no-op second time."""
    csv_path = tmp_path / "apps.csv"
    monkeypatch.setattr(tracker, "APPS_CSV", csv_path)

    # Write with expanded columns
    all_cols = tracker.COLUMNS + tracker.NEW_COLUMNS
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(all_cols)
        w.writerow(["acme", "eng", "de", "2024-01-01",
                     "generated", "", "",
                     "letters/x", "cv_x",
                     "3", "1", "gaps", "notes",
                     "de", "ats-cv", "scrlttr2-letter"])

    # First call migrates (or is no-op since already widened)
    tracker._ensure_header()
    # Second call — must be idempotent
    tracker._ensure_header()
    rows = tracker.list_applications()
    assert len(rows) == 1
    assert rows[0]["language"] == "de"


def test_update_application(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker, "APPS_CSV", tmp_path / "apps.csv")
    monkeypatch.setattr(tracker, "COLUMNS", tracker.COLUMNS)

    tracker.log_application(company="A")
    tracker.log_application(company="B")

    assert tracker.update_application(0, "status", "applied")  # newest = B
    rows = tracker.list_applications()
    assert rows[0]["company_name"] == "B"
    assert rows[0]["status"] == "applied"
    assert rows[1]["company_name"] == "A"
    assert rows[1]["status"] == "generated"


def test_update_latest_cv(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker, "APPS_CSV", tmp_path / "apps.csv")
    monkeypatch.setattr(tracker, "COLUMNS", tracker.COLUMNS)

    tracker.log_application(company="X")
    assert tracker.update_latest_cv("cv_new")
    rows = tracker.list_applications()
    assert rows[0]["cv_path"] == "cv_new"
