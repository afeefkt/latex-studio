# ── CV sidebar tests — skill ranking and language rendering ──
#
# The sidebar is what a recruiter reads first, and it silently went untailored
# for months because skill matching only ever looked at English bullet tags.
# These lock in the two things that broke: relevance detection and bar length.

from app.content import (
    SIDEBAR_SKILL_LIMIT,
    TIER_LEVEL,
    _group_bullets_by_role,
    _language_dots,
    _language_rows,
    _mentions,
    _sidebar_skill_limit,
    _split_skills,
)

FACTS = {
    "skills": {
        "expert": ["AUTOSAR Classic", "MATLAB/Simulink", "Python"],
        "proficient": ["ISO 26262 ASIL-B", "DOORS - Polarion - XCP"],
        "familiar": ["C#", "Java"],
    },
    "languages": [
        {"lang": "English", "level": "Professional"},
        {"lang": "German", "level": "B1 (BAMF Certified)"},
    ],
}


def _names(skills):
    return [s["name"] for s in skills]


def _level_of(skills, name):
    return next(s["level"] for s in skills if s["name"] == name)


# ── Bar length reflects proficiency, not JD relevance ──────────────────────────

def test_bar_level_comes_from_tier_not_relevance():
    """The old code rendered every matched skill at 90 and the rest at 50, so an
    expert skill the ad didn't name looked weaker than a familiar one it did."""
    matched, other = _split_skills(FACTS, [], jd_text="AUTOSAR Classic and Java")
    combined = matched + other
    assert _level_of(combined, "AUTOSAR Classic") == TIER_LEVEL["expert"]
    assert _level_of(combined, "Java") == TIER_LEVEL["familiar"]
    assert _level_of(combined, "ISO 26262 ASIL-B") == TIER_LEVEL["proficient"]


def test_matched_sorted_by_proficiency():
    matched, _ = _split_skills(FACTS, [], jd_text="Java AUTOSAR Classic")
    assert _names(matched) == ["AUTOSAR Classic", "Java"]


# ── Relevance: prose, phrases, and tags ────────────────────────────────────────

def test_job_ad_prose_drives_relevance():
    matched, other = _split_skills(FACTS, [], jd_text="We need MATLAB/Simulink experience")
    assert "MATLAB/Simulink" in _names(matched)
    assert "Java" in _names(other)


def test_matched_phrases_also_count():
    matched, _ = _split_skills(FACTS, [], jd_text="", matched_phrases=["strong Python background"])
    assert "Python" in _names(matched)


def test_bullet_tags_match_longer_skill_names():
    """Tags are short slugs; they must still match the fuller skill name."""
    role_groups = [{
        "tailored": True,
        "bullets": [{"tags": ["autosar", "iso26262"]}],
    }]
    matched, _ = _split_skills(FACTS, role_groups, jd_text="")
    assert "AUTOSAR Classic" in _names(matched)
    assert "ISO 26262 ASIL-B" in _names(matched)


def test_untailored_role_groups_are_ignored():
    role_groups = [{"tailored": False, "bullets": [{"tags": ["autosar"]}]}]
    matched, _ = _split_skills(FACTS, role_groups, jd_text="")
    # Falls back to expert tier rather than treating the untailored tag as a hit
    assert all(s["level"] == TIER_LEVEL["expert"] for s in matched)


def test_short_skill_does_not_match_unrelated_tag():
    """'C#' normalises to 'c', which must not match inside 'canoe'."""
    role_groups = [{"tailored": True, "bullets": [{"tags": ["canoe"]}]}]
    matched, _ = _split_skills(FACTS, role_groups, jd_text="")
    assert "C#" not in _names(matched)


def test_word_boundary_prevents_substring_false_positive():
    assert _mentions("we use JavaScript daily", "Java") is False
    assert _mentions("we use Java daily", "Java") is True
    assert _mentions("C# and .NET", "C#") is True


# ── Layout protection ──────────────────────────────────────────────────────────

def test_compound_skill_is_split_into_separate_entries():
    """One string of five tools became one overflowing bar with one rating."""
    matched, other = _split_skills(FACTS, [], jd_text="DOORS")
    all_names = _names(matched) + _names(other)
    assert "DOORS" in all_names
    assert "Polarion" in all_names
    assert "XCP" in all_names
    assert "DOORS - Polarion - XCP" not in all_names


def test_hyphen_without_spaces_is_not_split():
    matched, other = _split_skills(FACTS, [], jd_text="ISO 26262 ASIL-B")
    assert "ISO 26262 ASIL-B" in _names(matched) + _names(other)


def test_matched_is_capped_so_the_sidebar_cannot_overflow():
    facts = {"skills": {"expert": [f"Skill {i}" for i in range(30)]}}
    matched, other = _split_skills(facts, [], jd_text=" ".join(f"Skill {i}" for i in range(30)))
    assert len(matched) == SIDEBAR_SKILL_LIMIT
    assert len(other) == 30 - SIDEBAR_SKILL_LIMIT


def test_no_relevance_falls_back_to_strongest_skills():
    """A German ad naming none of the tools must still produce a sensible sidebar."""
    matched, _ = _split_skills(FACTS, [], jd_text="Kenntnisse in Elektrotechnik und Maschinenbau")
    assert _names(matched) == ["AUTOSAR Classic", "MATLAB/Simulink", "Python"]


def test_no_skill_appears_in_both_lists():
    matched, other = _split_skills(FACTS, [], jd_text="AUTOSAR Classic")
    assert set(_names(matched)).isdisjoint(_names(other))


# ── Languages ──────────────────────────────────────────────────────────────────

def test_cefr_level_maps_to_dots():
    assert _language_dots("B1 (BAMF Certified)") == 3
    assert _language_dots("C2") == 5
    assert _language_dots("A1") == 1


def test_worded_level_maps_to_dots():
    assert _language_dots("Professional") == 5
    assert _language_dots("Native speaker") == 5
    assert _language_dots("Basic") == 2


def test_unknown_level_is_mid_scale():
    assert _language_dots("") == 3
    assert _language_dots("something odd") == 3


def test_language_rows_cover_every_language():
    """The template used to hardcode if English / elif German and drop the rest."""
    facts = dict(FACTS, languages=[
        {"lang": "English", "level": "Professional"},
        {"lang": "German", "level": "B1"},
        {"lang": "Malayalam", "level": "Native"},
    ])
    rows = _language_rows(facts)
    assert [r["name"] for r in rows] == ["English", "German", "Malayalam"]
    assert rows[2]["dots"] == 5


def test_language_row_flag_falls_back_when_asset_missing():
    """A flag code is only emitted when the PNG actually ships with the templates."""
    rows = _language_rows({"languages": [{"lang": "Klingon", "level": "Fluent"}]})
    assert rows[0]["flag"] == ""


# ── Curated skill bars ─────────────────────────────────────────────────────────

CURATED = dict(FACTS, skill_bars=[
    {"name": "MBD - Matlab/Simulink/m-Scripting", "level": 90},
    {"name": "Embedded C / AUTOSAR / MISRA", "level": 70},
])


def test_curated_bars_lead_in_authored_order():
    """The author chose both the wording and the order; neither gets re-sorted."""
    bars, _ = _split_skills(CURATED, [], jd_text="Python")
    assert _names(bars)[:2] == [
        "MBD - Matlab/Simulink/m-Scripting",
        "Embedded C / AUTOSAR / MISRA",
    ]
    assert bars[0]["level"] == 90
    assert bars[1]["level"] == 70


def test_curated_name_is_not_split_on_its_dash():
    """_COMPOUND_SEP would shred a curated name and undo the author's grouping."""
    bars, other = _split_skills(CURATED, [], jd_text="")
    every = _names(bars) + _names(other)
    assert "MBD - Matlab/Simulink/m-Scripting" in every
    assert "MBD" not in every
    assert "Matlab/Simulink/m-Scripting" not in every


def test_jd_relevant_extras_appended_after_curated():
    """No curated bar covers ISO 26262, so the ad can still surface it — after
    the curated block, not interleaved into it."""
    bars, _ = _split_skills(CURATED, [], jd_text="experience with ISO 26262 ASIL-B required")
    assert "ISO 26262 ASIL-B" in _names(bars)
    assert _names(bars).index("ISO 26262 ASIL-B") > 1


def test_curated_bar_suppresses_the_skill_it_covers():
    """'MATLAB/Simulink' must not appear twice — the MBD bar already speaks for it."""
    bars, other = _split_skills(CURATED, [], jd_text="MATLAB/Simulink and Stateflow")
    every = _names(bars) + _names(other)
    assert "MATLAB/Simulink" not in every


def test_coverage_ignores_generic_words():
    """'Embedded Coder toolchain evaluation' shares only 'embedded' with a curated
    bar, which is far too generic to mean the bar covers it."""
    facts = dict(CURATED, skills={
        "expert": ["Embedded C"],
        "familiar": ["Embedded Coder toolchain evaluation"],
    })
    bars, other = _split_skills(facts, [], jd_text="")
    every = _names(bars) + _names(other)
    assert "Embedded Coder toolchain evaluation" in every
    # 'Embedded C' is spelled out in full by the curated bar, so it is covered
    assert "Embedded C" not in every


def test_curated_bars_respect_the_limit():
    facts = dict(FACTS, skill_bars=[
        {"name": f"Curated {i}", "level": 50} for i in range(20)
    ])
    bars, _ = _split_skills(facts, [], jd_text="")
    assert len(bars) == SIDEBAR_SKILL_LIMIT


def test_malformed_curated_entries_are_skipped():
    facts = dict(FACTS, skill_bars=[
        "just a string", {"level": 70}, {"name": "  "},
        {"name": "Good One", "level": "not a number"},
    ])
    bars, _ = _split_skills(facts, [], jd_text="")
    assert "Good One" in _names(bars)
    assert _level_of(bars, "Good One") == 70  # falls back rather than raising


# ── Sidebar budget ─────────────────────────────────────────────────────────────

def test_sidebar_budget_shrinks_for_photo_and_hobbies():
    """The sidebar drops overflow off the page silently, so space taken by the
    photo and hobbies has to be reserved before choosing how many bars to show."""
    assert _sidebar_skill_limit({}) == SIDEBAR_SKILL_LIMIT
    assert _sidebar_skill_limit({"identity": {"photo": "p.png"}}) == SIDEBAR_SKILL_LIMIT - 2
    assert _sidebar_skill_limit({"hobbies": ["a"]}) == SIDEBAR_SKILL_LIMIT - 3
    both = {"identity": {"photo": "p.png"}, "hobbies": ["a"]}
    assert _sidebar_skill_limit(both) == SIDEBAR_SKILL_LIMIT - 5


def test_sidebar_budget_never_collapses_to_nothing():
    facts = {"identity": {"photo": "p.png"}, "hobbies": ["a"]}
    assert _sidebar_skill_limit(facts) >= 3


def test_split_skills_uses_the_adaptive_budget():
    facts = dict(FACTS, identity={"photo": "p.png"}, hobbies=["chess"],
                 skills={"expert": [f"Skill {i}" for i in range(20)]})
    bars, _ = _split_skills(facts, [], jd_text=" ".join(f"Skill {i}" for i in range(20)))
    assert len(bars) == _sidebar_skill_limit(facts)


# ── Role grouping ──────────────────────────────────────────────────────────────

ROLE_FACTS = {
    "roles": [{
        "title": "Engineer", "org": "Acme", "start": "2020", "end": "2022",
        "tools": ["MATLAB", "Git"],
        "bullets": [
            {"id": "b1", "text": "first", "tags": ["autosar"]},
            {"id": "b2", "text": "second", "tags": ["canoe"]},
            {"id": "b3", "text": "third", "tags": ["python"]},
        ],
    }],
}


def test_all_bullets_shown_with_selected_first():
    """Showing only the selected bullets left the page half empty."""
    groups = _group_bullets_by_role(ROLE_FACTS, ["b3"])
    assert [b["id"] for b in groups[0]["bullets"]] == ["b3", "b1", "b2"]
    assert [b["selected"] for b in groups[0]["bullets"]] == [True, False, False]


def test_role_tools_are_carried_through():
    groups = _group_bullets_by_role(ROLE_FACTS, ["b1"])
    assert groups[0]["tools"] == ["MATLAB", "Git"]


def test_unselected_bullet_tags_do_not_dilute_skill_matching():
    """Retained roles now carry their unselected bullets, whose tags must not be
    mistaken for evidence that the job ad wanted those skills."""
    facts = dict(ROLE_FACTS, skills={"expert": ["AUTOSAR Classic", "CANoe", "Python"]})
    groups = _group_bullets_by_role(facts, ["b1"])
    bars, other = _split_skills(facts, groups, jd_text="")
    assert "AUTOSAR Classic" in _names(bars)          # tagged on the selected bullet
    assert "CANoe" in _names(other)                   # only on an unselected one
    assert "Python" in _names(other)
