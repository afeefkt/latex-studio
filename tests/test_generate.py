# ── /generate endpoint tests ──
#
# Uses a bare TestClient on the content router only.  app.main imports
# init_workspace() at module level which rebinds docs.WORKSPACE — calling
# app.main:app would defeat monkeypatching.  The content_router is an APIRouter,
# not a FastAPI app, so we create a minimal FastAPI with just that router.
#
# compile_doc is mocked because lualatex is not in CI.

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.content import router as content_router


class _FakeCompileResult:
    success = True
    errors = []


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient on the content router only, with a patched workspace."""
    import app.content as content_mod
    import app.docs as docs_mod

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "facts.yaml").write_text(
        "identity:\n  name: Tester\n  email: t@t.com\nroles: []\nskills: {expert: [], proficient: [], familiar: []}\n",
        encoding="utf-8",
    )
    (ws / "templates").mkdir()
    # Minimal scrtlttr2-letter template
    letter_tpl = ws / "templates" / "scrlttr2-letter"
    letter_tpl.mkdir()
    (letter_tpl / "template.json").write_text('{"name":"Cover Letter","kind":"letter","layout":"letter","requires":[],"variables":{}}')
    (letter_tpl / "main.tex.j2").write_text("\\documentclass{scrlttr2}\n\\begin{document}\\opening{\\VAR{ opening | tex_escape }}\\VAR{ edited_body | tex_escape }\\closing{\\VAR{ closing | tex_escape }}\\end{document}")
    # Minimal ats-cv template
    cv_tpl = ws / "templates" / "ats-cv"
    cv_tpl.mkdir()
    (cv_tpl / "template.json").write_text('{"name":"ATS CV","kind":"cv","layout":"ats","requires":[],"variables":{}}')
    (cv_tpl / "main.tex.j2").write_text("\\documentclass{article}\n\\begin{document}\\BLOCK{ for role in role_groups }\\VAR{ role.role_title | tex_escape }\\BLOCK{ endfor }\\end{document}")

    monkeypatch.setattr(content_mod, "PATHS_WORKSPACE", ws)
    monkeypatch.setattr(content_mod, "HOOKS_PATH", ws / "hooks.yaml")
    monkeypatch.setattr(content_mod, "CHROME_PATH", ws / "i18n" / "letter_chrome.yaml")
    monkeypatch.setattr(content_mod, "LABELS_PATH", ws / "i18n" / "labels.yaml")
    monkeypatch.setattr(content_mod, "TEMPLATES", ws / "templates")
    monkeypatch.setattr(docs_mod, "WORKSPACE", ws)
    monkeypatch.setattr(docs_mod, "TEMPLATES", ws / "templates")
    monkeypatch.setattr(docs_mod, "FACTS_PATH", ws / "facts.yaml")

    app = FastAPI()
    app.include_router(content_router)
    return TestClient(app), ws


# ── Input validation ───────────────────────────────────────────────────────────

def test_no_documents_returns_400(client):
    c, _ = client
    resp = c.post("/api/content/generate", json={"documents": []})
    assert resp.status_code == 400


def test_invalid_language_returns_400(client):
    c, _ = client
    resp = c.post("/api/content/generate", json={
        "documents": ["letter"], "language": "xx",
    })
    assert resp.status_code == 400


def test_unknown_template_returns_400(client):
    c, _ = client
    resp = c.post("/api/content/generate", json={
        "documents": ["cv"], "cv_template": "nonexistent",
    })
    assert resp.status_code == 400


def test_traversal_template_returns_400(client):
    c, _ = client
    resp = c.post("/api/content/generate", json={
        "documents": ["cv"], "cv_template": "../../../etc",
    })
    assert resp.status_code == 400


def test_wrong_kind_template_returns_400(client):
    """Using a letter template where a CV is expected → 400."""
    c, _ = client
    resp = c.post("/api/content/generate", json={
        "documents": ["cv"], "cv_template": "scrlttr2-letter",
    })
    assert resp.status_code == 400


# ── Generate success paths ─────────────────────────────────────────────────────

@patch("app.content.compile_doc", new_callable=AsyncMock)
def test_generate_both(mock_compile, client):
    mock_compile.return_value = _FakeCompileResult()
    c, ws = client
    resp = c.post("/api/content/generate", json={
        "documents": ["letter", "cv"],
        "company_name": "Acme", "role_title": "Eng", "location": "Berlin",
        "hook_key": "exact_match", "focus_phrase": "testing",
    })
    assert resp.status_code == 200
    out = resp.json()
    assert out["created"] is True
    assert out["letter"] is not None
    assert out["cv"] is not None
    assert out["documents"] == ["letter", "cv"]


@patch("app.content.compile_doc", new_callable=AsyncMock)
def test_generate_cv_only(mock_compile, client):
    """CV only → letter key is null in response."""
    mock_compile.return_value = _FakeCompileResult()
    c, ws = client
    resp = c.post("/api/content/generate", json={
        "documents": ["cv"],
        "company_name": "Acme", "role_title": "Eng",
    })
    assert resp.status_code == 200
    out = resp.json()
    assert out["letter"] is None
    assert out["cv"] is not None
    assert out["documents"] == ["cv"]


@patch("app.content.compile_doc", new_callable=AsyncMock)
def test_generate_letter_only(mock_compile, client):
    mock_compile.return_value = _FakeCompileResult()
    c, ws = client
    resp = c.post("/api/content/generate", json={
        "documents": ["letter"],
        "company_name": "Acme", "role_title": "Eng",
        "hook_key": "exact_match", "focus_phrase": "testing",
    })
    assert resp.status_code == 200
    out = resp.json()
    assert out["letter"] is not None
    assert out["cv"] is None


# ── Write gate ─────────────────────────────────────────────────────────────────

@patch("app.content.compile_doc", new_callable=AsyncMock)
def test_edited_body_with_banned_claim_returns_422(mock_compile, client):
    """'security clearance' is in the fixture's banned_claims → 422."""
    mock_compile.return_value = _FakeCompileResult()
    c, ws = client
    facts = {
        "identity": {"name": "T", "email": "t@t.com", "phone": ""},
        "roles": [{"title": "Eng", "org": "ACME", "start": "2020", "end": "2023",
                    "bullets": [{"id": "b1", "text": "Built things", "tags": ["python"]}]}],
        "skills": {"expert": ["Python"], "proficient": [], "familiar": []},
        "education": [], "languages": [], "awards": [], "hobbies": [],
        "banned_claims": ["security clearance", "istqb"],
        "certifications_held": [],
        "certifications_in_progress": [],
    }
    (ws / "facts.yaml").write_text(
        f"identity:\n  name: T\n  email: t@t.com\n  phone: ''\nroles:\n  - title: Eng\n    org: ACME\n    start: '2020'\n    end: '2023'\n    bullets:\n      - id: b1\n        text: 'Built things'\n        tags: [python]\nskills:\n  expert: [Python]\n  proficient: []\n  familiar: []\neducation: []\nlanguages: []\nawards: []\nhobbies: []\nbanned_claims:\n  - security clearance\n  - istqb\ncertifications_held: []\ncertifications_in_progress: []\n",
        encoding="utf-8",
    )
    # Invalidate module cache so load_factbank picks up the new file
    import importlib, app.guard.factbank
    importlib.reload(app.guard.factbank)

    resp = c.post("/api/content/generate", json={
        "documents": ["letter"],
        "company_name": "Acme", "role_title": "Eng",
        "hook_key": "exact_match", "focus_phrase": "Python",
        "selected_bullet_ids": ["b1"],
        "edited_body": "I hold a security clearance.",
    })
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert any("security clearance" in e["message"] for e in detail.get("errors", []))
