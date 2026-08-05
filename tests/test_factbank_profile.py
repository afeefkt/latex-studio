# ── Regression tests: fact bank / facts.yaml must stay in sync ──
#
# Guards the failure that produced "Rule 2: No bullet text resolved from
# selected_bullet_ids": the guard validated fact_ids against workspace/facts.yaml
# while the letter was assembled from workspace/<profile>/facts.yaml. IDs passed
# rule 2, then resolved to no bullet text.

import pytest
import yaml
from fastapi.testclient import TestClient

import app.docs as docs
from app.content import _expand_role_ids_to_bullets, _get_bullet_texts
from app.guard.factbank import _facts_path, load_factbank

FACTS = {
    "identity": {"name": "Test User"},
    "roles": [
        {
            "id": "acme",
            "org": "Acme GmbH",
            "title": "Engineer",
            "bullets": [
                {"id": "acme_one", "text": "Did the first thing."},
                {"id": "acme_two", "text": "Did the second thing."},
            ],
        }
    ],
}


@pytest.fixture
def profile_ws(tmp_path, monkeypatch):
    """A workspace with an active profile, mirroring the real layout."""
    profile = tmp_path / "default"
    profile.mkdir(parents=True)
    (profile / "facts.yaml").write_text(yaml.dump(FACTS), encoding="utf-8")
    # Root facts.yaml deliberately differs — if anything reads this one instead
    # of the profile's, the assertions below catch it.
    (tmp_path / "facts.yaml").write_text(yaml.dump({"roles": []}), encoding="utf-8")

    monkeypatch.setattr(docs, "WORKSPACE", profile)
    monkeypatch.setattr(docs, "FACTS_PATH", profile / "facts.yaml")
    return profile


def test_factbank_follows_active_profile(profile_ws):
    """load_factbank() must read the profile's facts.yaml, not the root one."""
    assert _facts_path() == docs.FACTS_PATH
    assert "acme_one" in load_factbank().all_fact_ids


def test_every_guard_id_resolves_to_bullet_text(profile_ws):
    """Any id accepted by rule 2 must either resolve to bullet text or expand
    to ids that do. Otherwise the guard passes and the letter comes out empty."""
    facts = yaml.safe_load(docs.FACTS_PATH.read_text(encoding="utf-8"))
    for fid in sorted(load_factbank().all_fact_ids):
        expanded = _expand_role_ids_to_bullets(facts, [fid])
        assert _get_bullet_texts(facts, expanded), f"{fid!r} resolves to no bullet text"


def test_role_id_expands_to_its_bullets(profile_ws):
    facts = yaml.safe_load(docs.FACTS_PATH.read_text(encoding="utf-8"))
    assert _expand_role_ids_to_bullets(facts, ["acme"]) == ["acme_one", "acme_two"]
    # Bullet ids pass through; duplicates collapse; unknown ids are dropped.
    assert _expand_role_ids_to_bullets(facts, ["acme_one", "acme"]) == ["acme_one", "acme_two"]
    assert _expand_role_ids_to_bullets(facts, ["nope"]) == []


def test_error_body_cannot_overwrite_facts():
    """The 404 body {"detail": ...} is valid YAML and parses to a dict. It must
    still be refused — that payload is what destroyed the real facts.yaml."""
    from app.main import app

    client = TestClient(app)
    resp = client.post("/api/facts/raw", json={"yaml_text": "detail: facts.yaml not found"})
    assert resp.status_code == 400
    assert "no recognised facts.yaml sections" in resp.json()["detail"]
