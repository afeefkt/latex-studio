# ── CV translation extract/substitute tests ──
#
# The risk this module carries is silent misattribution: a key scheme that
# drifts between collect and apply puts one role's translated bullet under a
# different role, and the output still compiles and still looks plausible.
# These tests pin the round-trip.

import copy

from app.cv_translate import apply_cv_strings, collect_cv_strings


def _vars() -> dict:
    facts = {
        "identity": {
            "name": "Afeef Kallanthodan",
            "email": "a@b.com",
            "title": "Embedded Software Engineer",
            "about": "Engineer with 8+ years across AUTOSAR and ISO 26262.",
            "nationality": "Indian",
            "work_authorisation": "EU Blue Card",
        },
        "roles": [
            {
                "title": "Embedded SW Engineer", "org": "KooSys GmbH",
                "location": "Regensburg", "start": "Sep 2024", "end": "Present",
                "duration": "1 year", "tools": ["MATLAB/Simulink", "CANoe"],
                "bullets": [
                    {"id": "koosys_foc", "text": "Developed FOC algorithms.", "tags": ["mbd"]},
                    {"id": "koosys_plant", "text": "Built a plant model.", "tags": ["sim"]},
                ],
            },
            {
                "title": "MBD Engineer", "org": "TATA Elxsi Ltd.",
                "location": "Bangalore", "start": "Jul 2021", "end": "Mar 2023",
                "duration": "1 year 8 months", "tools": ["Polyspace"],
                "bullets": [
                    {"id": "tata_eps", "text": "Developed EPS components.", "tags": ["autosar"]},
                ],
            },
        ],
        "education": [
            {"degree": "B.Tech Mechanical Engineering",
             "institution": "Mahatma Gandhi University",
             "focus": "Mechatronics and control systems", "years": "2011 -- 2015"},
        ],
        "awards": [
            {"title": "Extra Mile Award", "org": "TATA Elxsi Ltd.",
             "description": "Awarded for delivering on schedule.", "year": 2022},
        ],
        "hobbies": ["Real Simulation Games", "AI Enthusiast"],
        "languages": [
            {"lang": "English", "level": "Professional"},
            {"lang": "German", "level": "B1 (BAMF Certified)"},
        ],
        "skills": {"expert": ["MATLAB/Simulink"], "proficient": [], "familiar": []},
    }
    return {
        "facts": facts,
        "role_groups": [
            {
                "role_title": "Embedded SW Engineer", "org": "KooSys GmbH",
                "location": "Regensburg", "start": "Sep 2024", "end": "Present",
                "duration": "1 year", "dates": "Sep 2024 – Present",
                "tools": ["MATLAB/Simulink", "CANoe"], "tailored": True,
                "bullets": [
                    {"id": "koosys_foc", "text": "Developed FOC algorithms.",
                     "tags": ["mbd"], "selected": True},
                    {"id": "koosys_plant", "text": "Built a plant model.",
                     "tags": ["sim"], "selected": False},
                ],
            },
            {
                "role_title": "MBD Engineer", "org": "TATA Elxsi Ltd.",
                "location": "Bangalore", "start": "Jul 2021", "end": "Mar 2023",
                "duration": "1 year 8 months", "dates": "Jul 2021 – Mar 2023",
                "tools": ["Polyspace"], "tailored": False,
                "bullets": [
                    {"id": "tata_eps", "text": "Developed EPS components.",
                     "tags": ["autosar"], "selected": False},
                ],
            },
        ],
        "language_rows": [
            {"name": "English", "level": "Professional", "dots": 5, "flag": ""},
            {"name": "German", "level": "B1 (BAMF Certified)", "dots": 3, "flag": "DE"},
        ],
        "matched_skills": [{"name": "MATLAB/Simulink", "level": "expert"}],
        "other_skills": [],
        "language": "de",
        "babel_lang": "ngerman",
        "L": {},
    }


# ── Collection ────────────────────────────────────────────────────────────────

def test_collects_every_translatable_field():
    got = collect_cv_strings(_vars())
    assert got["about"].startswith("Engineer with 8+")
    assert got["jobtitle"] == "Embedded Software Engineer"
    assert got["nationality"] == "Indian"
    assert got["work_auth"] == "EU Blue Card"
    assert got["bullet.koosys_foc"] == "Developed FOC algorithms."
    assert got["bullet.koosys_plant"] == "Built a plant model."
    assert got["bullet.tata_eps"] == "Developed EPS components."
    assert got["edu.0.degree"] == "B.Tech Mechanical Engineering"
    assert got["edu.0.focus"] == "Mechatronics and control systems"
    assert got["award.0.title"] == "Extra Mile Award"
    assert got["award.0.description"] == "Awarded for delivering on schedule."
    assert got["hobby.0"] == "Real Simulation Games"
    assert got["hobby.1"] == "AI Enthusiast"
    assert got["lang.0.name"] == "English"
    assert got["lang.1.level"] == "B1 (BAMF Certified)"


def test_proper_nouns_are_never_collected():
    """Names, employers, institutions, cities, tools and emails must not be sent
    to a translator — they are the fact bank's identity anchors."""
    values = set(collect_cv_strings(_vars()).values())
    for proper_noun in (
        "Afeef KT", "a@b.com", "KooSys GmbH", "TATA Elxsi Ltd.",
        "Mahatma Gandhi University", "Regensburg", "Bangalore",
        "MATLAB/Simulink", "CANoe", "Polyspace",
    ):
        assert proper_noun not in values


def test_role_key_is_shared_between_both_role_views():
    """facts.roles and role_groups must address the same role by the same key,
    otherwise one view translates and the other silently does not."""
    got = collect_cv_strings(_vars())
    role_title_keys = [k for k in got if k.endswith(".title") and k.startswith("role.")]
    # Two roles, one key each — not four.
    assert len(role_title_keys) == 2


# ── Substitution ──────────────────────────────────────────────────────────────

def test_apply_translates_both_role_views_consistently():
    v = _vars()
    out = apply_cv_strings(v, {
        "bullet.koosys_foc": "FOC-Algorithmen entwickelt.",
        "bullet.tata_eps": "EPS-Komponenten entwickelt.",
    })
    facts_texts = [b["text"] for r in out["facts"]["roles"] for b in r["bullets"]]
    group_texts = [b["text"] for r in out["role_groups"] for b in r["bullets"]]
    assert "FOC-Algorithmen entwickelt." in facts_texts
    assert "FOC-Algorithmen entwickelt." in group_texts
    assert "EPS-Komponenten entwickelt." in facts_texts
    assert "EPS-Komponenten entwickelt." in group_texts


def test_bullets_stay_under_their_own_role():
    """The misattribution case: a translated bullet must not migrate roles."""
    out = apply_cv_strings(_vars(), {
        "bullet.koosys_foc": "KOOSYS-BULLET",
        "bullet.tata_eps": "TATA-BULLET",
    })
    by_org = {r["org"]: [b["text"] for b in r["bullets"]] for r in out["role_groups"]}
    assert "KOOSYS-BULLET" in by_org["KooSys GmbH"]
    assert "KOOSYS-BULLET" not in by_org["TATA Elxsi Ltd."]
    assert "TATA-BULLET" in by_org["TATA Elxsi Ltd."]
    assert "TATA-BULLET" not in by_org["KooSys GmbH"]


def test_missing_keys_fall_back_to_english():
    """A partial translator response degrades to partly-English, never to blank."""
    out = apply_cv_strings(_vars(), {"bullet.koosys_foc": "Uebersetzt."})
    texts = [b["text"] for r in out["role_groups"] for b in r["bullets"]]
    assert "Uebersetzt." in texts
    assert "Built a plant model." in texts          # untranslated, still present
    assert out["facts"]["identity"]["about"].startswith("Engineer with 8+")


def test_blank_translation_falls_back_to_english():
    out = apply_cv_strings(_vars(), {"about": "   ", "jobtitle": ""})
    assert out["facts"]["identity"]["about"].startswith("Engineer with 8+")
    assert out["facts"]["identity"]["title"] == "Embedded Software Engineer"


def test_derived_dates_rebuilt_from_translated_end():
    """'Present' → 'Heute' must reach templates that render the date range."""
    out = apply_cv_strings(_vars(), {"role.koosysgmbhsep2024.end": "Heute"})
    koosys = next(r for r in out["role_groups"] if r["org"] == "KooSys GmbH")
    assert koosys["end"] == "Heute"
    assert koosys["dates"] == "Sep 2024 – Heute"


def test_apply_does_not_mutate_the_caller_facts():
    """The letter spec renders from the same facts dict in the same request."""
    v = _vars()
    before = copy.deepcopy(v["facts"])
    apply_cv_strings(v, {"about": "Deutscher Text.", "bullet.koosys_foc": "Deutsch."})
    assert v["facts"] == before


def test_empty_map_is_a_noop():
    v = _vars()
    assert apply_cv_strings(v, {}) is v


def test_scalar_fields_translate():
    out = apply_cv_strings(_vars(), {
        "about": "Ingenieur mit 8+ Jahren.",
        "jobtitle": "Embedded-Softwareentwickler",
        "nationality": "Indisch",
        "work_auth": "Blaue Karte EU",
        "edu.0.degree": "B.Tech Maschinenbau",
        "award.0.title": "Extra Mile Auszeichnung",
        "hobby.0": "Simulationsspiele",
        "lang.0.name": "Englisch",
        "lang.0.level": "Verhandlungssicher",
    })
    ident = out["facts"]["identity"]
    assert ident["about"] == "Ingenieur mit 8+ Jahren."
    assert ident["title"] == "Embedded-Softwareentwickler"
    assert ident["nationality"] == "Indisch"
    assert ident["work_authorisation"] == "Blaue Karte EU"
    assert out["facts"]["education"][0]["degree"] == "B.Tech Maschinenbau"
    assert out["facts"]["awards"][0]["title"] == "Extra Mile Auszeichnung"
    assert out["facts"]["hobbies"][0] == "Simulationsspiele"
    assert out["language_rows"][0]["name"] == "Englisch"
    assert out["language_rows"][0]["level"] == "Verhandlungssicher"
    assert out["facts"]["languages"][0]["lang"] == "Englisch"


def test_untouched_fields_survive():
    """Employers, institutions, tools and contact details pass through intact."""
    out = apply_cv_strings(_vars(), {"about": "Deutsch.", "bullet.koosys_foc": "Deutsch."})
    koosys = next(r for r in out["role_groups"] if r["org"] == "KooSys GmbH")
    assert koosys["org"] == "KooSys GmbH"
    assert koosys["location"] == "Regensburg"
    assert koosys["tools"] == ["MATLAB/Simulink", "CANoe"]
    assert out["facts"]["identity"]["name"] == "Afeef Kallanthodan"
    assert out["facts"]["identity"]["email"] == "a@b.com"
    assert out["facts"]["education"][0]["institution"] == "Mahatma Gandhi University"
    assert out["facts"]["awards"][0]["org"] == "TATA Elxsi Ltd."


def test_round_trip_identity():
    """Applying the collected English map back is a no-op on every value."""
    v = _vars()
    out = apply_cv_strings(v, collect_cv_strings(v))
    assert out["facts"]["identity"]["about"] == v["facts"]["identity"]["about"]
    assert [b["text"] for r in out["role_groups"] for b in r["bullets"]] == \
           [b["text"] for r in v["role_groups"] for b in r["bullets"]]
    assert out["facts"]["hobbies"] == v["facts"]["hobbies"]
