# ── Phase 6: Content mode — JD parsing + fact-matching + letter assembly ──

import json
import logging
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.compile import compile_doc
from app.docs import TEMPLATES, create_document, load_facts, render_template, tex_escape
from app.guard.factbank import load_factbank
from app.guard.validator import validate_assembled_text, validate_tailor_response
from app.llm.provider import get_provider
from app.tracker import log_application, update_latest_cv

logger = logging.getLogger("latex_studio.content")
router = APIRouter(prefix="/api/content", tags=["content"])

CONTENT_PROMPT_PATH = Path(__file__).parent / "llm" / "prompts" / "content_mode.md"
_prompt_cache: str | None = None


def _load_content_prompt() -> str:
    global _prompt_cache
    if _prompt_cache is None:
        if CONTENT_PROMPT_PATH.exists():
            _prompt_cache = CONTENT_PROMPT_PATH.read_text(encoding="utf-8")
        else:
            _prompt_cache = "You are a career document assistant."
    return _prompt_cache


HOOKS_PATH = Path(__file__).parent.parent / "workspace" / "hooks.yaml"


def _load_hooks() -> dict:
    """Load the pre-written opening hooks. Not cached — edit hooks.yaml and re-run."""
    if not HOOKS_PATH.exists():
        return {}
    import yaml as _yaml
    return _yaml.safe_load(HOOKS_PATH.read_text(encoding="utf-8")) or {}


def _build_hook_text(hook_key: str, company_name: str, role_title: str, focus_phrase: str) -> str:
    """
    Render the opening paragraph for a validated hook_key.

    The hook prose is human-authored (workspace/hooks.yaml); the model only selects
    which key applies, and guard rule 4 has already checked the key is in the enum.
    Slot values are LaTeX-escaped before substitution, so the result is already safe
    and must NOT be passed through tex_escape again in the template.

    Uses replace() rather than format() so braces in hook prose don't blow up.
    """
    hooks = _load_hooks()
    template = hooks.get(hook_key, "")
    if not template:
        logger.warning(f"No hook text for hook_key '{hook_key}' — opening paragraph omitted")
        return ""

    for slot, value in (
        ("{company_name}", company_name),
        ("{role_title}", role_title),
        ("{focus_phrase}", focus_phrase),
    ):
        template = template.replace(slot, tex_escape(value))
    return " ".join(template.split())


def score_fit(matched: list[dict], unmatched: list[str], requirements: list[dict] | None = None) -> dict:
    """
    Score how well the candidate fits this job. Pure Python — no LLM.

    A model grading its own match quality is not a control, the same reasoning that
    keeps the guard regex-only (spec 8.4). matched_requirements and
    unmatched_requirements already partition the JD, so no extra call is needed.

    Confidence-weighted: three 0.9 matches beat three 0.4 matches even though both
    cover the same number of requirements.

    Score and hard requirements are kept as SEPARATE signals rather than folded into
    one number. The score answers "how much of what they asked for can I evidence?"
    Hard requirements (certification, education, language) then act as a gate: you
    cannot talk your way past a missing licence the way you can past a missing tool,
    so a hard gap caps the verdict at STRETCH no matter how high the coverage. Mixing
    the two into one arithmetic left the number meaning nothing explainable.

    Thresholds are deliberately generous. Job ads are wish lists, and the standard
    advice is to apply at around 60% — a scorer that says SKIP too readily just
    talks you out of jobs you would have got.
    """
    HARD = {"certification", "education", "language"}

    category_of: dict[str, str] = {}
    for r in requirements or []:
        phrase = (r.get("phrase") or "").strip().lower()
        if phrase:
            category_of[phrase] = (r.get("category") or "").strip().lower()

    hard_gaps = [
        str(g) for g in unmatched
        if category_of.get(str(g).strip().lower()) in HARD
    ]

    total = len(matched) + len(unmatched)
    if total == 0:
        return {"score": 0, "band": "UNKNOWN",
                "reason": "No requirements were parsed from this job ad.",
                "hard_gaps": []}

    earned = sum(float(m.get("confidence", 0) or 0) for m in matched)
    score = round((earned / total) * 100)

    if score >= 55:
        band, reason = "STRONG", "Strong fit — worth applying."
    elif score >= 35:
        band, reason = "STRETCH", "Stretch — apply if you want it, and lead with the transferable angle."
    else:
        band, reason = "SKIP", "Weak fit — your evening is probably better spent on another posting."

    # A missing hard requirement gates the verdict down, but never up.
    if hard_gaps and band == "STRONG":
        band = "STRETCH"
        reason = (
            f"You cover most of this, but {hard_gaps[0]} is a hard requirement you "
            f"don't have. Worth applying if they'll flex on it — say nothing that implies you do."
        )
    elif hard_gaps:
        reason += f" Hard gap: {', '.join(hard_gaps[:2])}."

    return {"score": score, "band": band, "reason": reason, "hard_gaps": hard_gaps}


class TailorRequest(BaseModel):
    job_ad_text: str
    provider: str | None = None
    model: str | None = None


class OptimizeCvRequest(BaseModel):
    selected_bullet_ids: list[str]
    optimized_bullets: list[dict] = []


@router.post("/tailor")
async def tailor_letter(body: TailorRequest):
    job_ad = body.job_ad_text.strip()
    provider = body.provider
    model = body.model

    if not job_ad:
        raise HTTPException(400, "Job ad text is required")

    facts = load_facts()
    if not facts:
        raise HTTPException(400, "facts.yaml not found or empty — create one from facts.example.yaml")

    factbank = load_factbank()

    # Build the prompt: system + facts + schema (cached prefix) + JD (variable suffix)
    system_prompt = _load_content_prompt()
    facts_yaml_block = yaml_dump_facts(facts)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Here is the candidate's facts.yaml:\n\n```yaml\n{facts_yaml_block}\n```"},
        {"role": "assistant", "content": "I understand the candidate's background. Send me a job description and I'll tailor a response."},
        {"role": "user", "content": f"Here is the job description:\n\n{job_ad}\n\nParse the JD, match to facts, and return the JSON."},
    ]

    async def event_generator():
        llm = None
        try:
            yield f"event: status\ndata: {json.dumps({'stage': 'parse', 'message': 'Asking LLM to parse JD and match to your experience...'})}\n\n"

            llm = get_provider(provider, model)
            full = ""
            async for token in llm.chat(messages, stream=True):
                full += token
                yield f"data: {json.dumps({'token': token})}\n\n"

            logger.info(f"Content mode: LLM returned {len(full)} chars")

            # Extract JSON from response
            json_match = re.search(r"```json\s*([\s\S]*?)```", full)
            if json_match:
                json_str = json_match.group(1).strip()
            else:
                # Try bare JSON
                json_str = full.strip()

            try:
                parsed = json.loads(json_str)
            except json.JSONDecodeError as e:
                yield f"event: error\ndata: {json.dumps({'error': f'Failed to parse LLM response as JSON: {e}'})}\n\n"
                return

            # Extract TailorResponse fields from parsed JSON
            tailor_data = {
                "matched_requirements": parsed.get("matched_requirements", []),
                "selected_bullet_ids": parsed.get("selected_bullet_ids", []),
                "focus_phrase": parsed.get("focus_phrase", ""),
                "hook_key": parsed.get("hook_key", ""),
                "unmatched_requirements": parsed.get("unmatched_requirements", []),
                "notes_for_human": parsed.get("notes_for_human", ""),
            }

            # Parsed JD requirements carry a `category` used to weight hard gaps.
            # Kept out of tailor_data so the guard's schema check stays unchanged.
            jd_requirements = parsed.get("requirements", [])

            yield f"event: status\ndata: {json.dumps({'stage': 'guard', 'message': 'Validating structure against facts.yaml...'})}\n\n"

            # ── Guard pass 1: structure only (rules 1-4). Fail fast on bad JSON/IDs. ──
            validation = validate_tailor_response(tailor_data, job_ad, factbank)
            if not validation.passed:
                guard_errors = [
                    {"rule": e.rule, "message": e.message, "detail": e.detail}
                    for e in validation.errors
                ]
                yield f"event: stage\ndata: {json.dumps({'stage': 'guard_failed', 'errors': guard_errors, 'warnings': [{'rule': w.rule, 'message': w.message} for w in validation.warnings]})}\n\n"
                yield f"event: done\ndata: {json.dumps({'success': False, 'message': 'Guard rejected the response. Check the errors above.'})}\n\n"
                return

            # Assemble the letter body
            yield f"event: status\ndata: {json.dumps({'stage': 'assemble', 'message': 'Assembling letter...'})}\n\n"

            bullet_ids = tailor_data["selected_bullet_ids"]
            bullet_texts = _get_bullet_texts(facts, bullet_ids)

            # A role id passes rule 2 but resolves to no bullet text — catch the
            # silent-empty-letter case rather than rendering a body-less letter.
            if not bullet_texts:
                yield f"event: stage\ndata: {json.dumps({'stage': 'guard_failed', 'errors': [{'rule': 2, 'message': 'No bullet text resolved from selected_bullet_ids', 'detail': f'IDs given: {bullet_ids}. These may be role ids rather than bullet ids.'}], 'warnings': []})}\n\n"
                yield f"event: done\ndata: {json.dumps({'success': False, 'message': 'Selected IDs produced an empty letter body.'})}\n\n"
                return

            # Apply optimized bullets — LLM-rewritten prose. This is generated text,
            # so the assembled result MUST go through guard pass 2 below.
            optimized = {o["id"]: o["text"] for o in parsed.get("optimized_bullets", []) if "id" in o and "text" in o}
            for i, bt in enumerate(bullet_texts):
                if bt["id"] in optimized:
                    bullet_texts[i]["text"] = optimized[bt["id"]]

            # ── Guard pass 2: rules 5-9 on the assembled body text ──
            # Without this, banned claims, invented numbers, false certifications and
            # hallucinated tools introduced via optimized_bullets reach the letter.
            yield f"event: status\ndata: {json.dumps({'stage': 'guard2', 'message': 'Validating letter text against facts.yaml...'})}\n\n"

            assembled_body = "\n".join(bt["text"] for bt in bullet_texts)
            validation = validate_tailor_response(
                tailor_data, job_ad, factbank, assembled_text=assembled_body
            )
            if not validation.passed:
                guard_errors = [
                    {"rule": e.rule, "message": e.message, "detail": e.detail}
                    for e in validation.errors
                ]
                yield f"event: stage\ndata: {json.dumps({'stage': 'guard_failed', 'errors': guard_errors, 'warnings': [{'rule': w.rule, 'message': w.message} for w in validation.warnings]})}\n\n"
                yield f"event: done\ndata: {json.dumps({'success': False, 'message': 'Guard rejected the assembled letter text. Check the errors above.'})}\n\n"
                return

            if validation.warnings:
                yield f"event: stage\ndata: {json.dumps({'stage': 'guard_warnings', 'warnings': [{'rule': w.rule, 'message': w.message} for w in validation.warnings]})}\n\n"

            company_name = parsed.get("company_name", "the company")
            role_title = parsed.get("role_title", "this position")
            location = parsed.get("location", "")
            focus_phrase = tailor_data.get("focus_phrase", "")
            hook_key = tailor_data.get("hook_key", "")

            # Build template variables
            identity = facts.get("identity", {})
            template_vars = {
                "sender_name": identity.get("name", ""),
                "sender_address": identity.get("address", identity.get("location", "")),
                "sender_email": identity.get("email", ""),
                "sender_phone": identity.get("phone", ""),
                "recipient_name": f"Hiring Manager at {company_name}",
                "recipient_company": company_name,
                "recipient_address": location,
                "subject": f"Application for {role_title}",
                "opening": f"Dear Hiring Team at {company_name},",
                "closing": "Sincerely,",
                "selected_bullets": bullet_texts,
                "company_name": company_name,
                "role_title": role_title,
                "focus_phrase": focus_phrase,
                "hook_key": hook_key,
                "hook_text": _build_hook_text(hook_key, company_name, role_title, focus_phrase),
                "about_company": f"at {company_name}",
            }

            # Render the letter template
            try:
                letter_tex = render_template("scrlttr2-letter", template_vars)
            except Exception as e:
                yield f"event: error\ndata: {json.dumps({'error': f'Template rendering failed: {e}'})}\n\n"
                return

            # NOTHING is written to disk here. Analysis is free to run on jobs you
            # end up skipping; documents and the tracker row are created only when
            # the user picks a channel in /generate (spec 8.5 human-in-the-loop, and
            # it keeps the workspace from filling with letters for jobs never applied to).

            matched_out = [
                {'phrase': mr.get('jd_phrase', ''), 'confidence': mr.get('confidence', 0)}
                for mr in tailor_data.get('matched_requirements', [])
            ]
            fit = score_fit(
                tailor_data.get('matched_requirements', []),
                tailor_data.get('unmatched_requirements', []),
                jd_requirements,
            )

            yield f"event: done\ndata: {json.dumps({
                'success': True,
                'fit_score': fit['score'],
                'fit_band': fit['band'],
                'fit_reason': fit['reason'],
                'hard_gaps': fit['hard_gaps'],
                'location': location,
                'company_name': company_name,
                'role_title': role_title,
                'letter_preview': letter_tex[:500],
                'assembled_body': assembled_body,
                'focus_phrase': focus_phrase,
                'hook_key': hook_key,
                'selected_bullet_ids': tailor_data.get('selected_bullet_ids', []),
                'optimized_bullets': parsed.get('optimized_bullets', []),
                'matched': matched_out,
                'unmatched': tailor_data.get('unmatched_requirements', []),
                'notes': tailor_data.get('notes_for_human', ''),
            })}\n\n"

        except ValueError as e:
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
        except Exception as e:
            logger.error(f"Content mode error: {e}")
            yield f"event: error\ndata: {json.dumps({'error': f'Tailoring failed: {e}'})}\n\n"
        finally:
            if llm is not None:
                try:
                    await llm.close()
                except Exception:
                    pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class GenerateRequest(BaseModel):
    """Everything /tailor returned, plus the channel the user picked."""
    channel: str = "portal"                  # "portal" (ATS-safe) | "email" (designed)
    cv_template: str = ""                    # template ID to use for CV (defaults based on channel)
    company_name: str = ""
    role_title: str = ""
    location: str = ""
    focus_phrase: str = ""
    hook_key: str = ""
    selected_bullet_ids: list[str] = []
    optimized_bullets: list[dict] = []
    unmatched: list[str] = []
    matched_count: int = 0
    notes: str = ""
    edited_body: str | None = None           # Hand-edited letter body from preview step
    job_ad_text: str = ""                    # Ranks CV skills by relevance to this ad
    matched_phrases: list[str] = []          # JD phrases the LLM matched, for the same ranking


def _slugify(text: str, fallback: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-") or fallback


def _create_unique(base_name: str, template_id: str, variables: dict) -> dict:
    """create_document, retrying with a numeric suffix when the folder already exists."""
    name = base_name
    for attempt in range(2, 100):
        try:
            return create_document(name, template_id, variables)
        except FileExistsError:
            name = f"{base_name}-{attempt}"
    raise HTTPException(500, f"Could not find a free document name for '{base_name}'")


def _pdf_filename(person: str, kind: str, company: str) -> str:
    """Afeef_KT_CV_Vibracoustic.pdf — what a recruiter should see in their inbox."""
    def clean(s: str) -> str:
        return re.sub(r"[^A-Za-z0-9]+", "_", (s or "").strip()).strip("_")
    parts = [clean(person) or "CV", kind, clean(company)]
    return "_".join(p for p in parts if p) + ".pdf"


@router.post("/generate")
async def generate_documents(body: GenerateRequest):
    """
    Create the cover letter and the CV in the variant matching the chosen channel,
    compile both, log the application, and hand back download links.

    This is the only place documents are written. /tailor just analyses.
    """
    facts = load_facts()
    if not facts:
        raise HTTPException(400, "facts.yaml not found or empty")

    identity = facts.get("identity", {})
    person = identity.get("name", "")
    company = body.company_name or "the company"
    role = body.role_title or "this position"

    bullet_texts = _get_bullet_texts(facts, body.selected_bullet_ids)
    if not bullet_texts:
        raise HTTPException(400, "No bullet text resolved from the selected IDs")

    optimized_map = {
        o["id"]: o["text"] for o in body.optimized_bullets if "id" in o and "text" in o
    }
    for bt in bullet_texts:
        if bt["id"] in optimized_map:
            bt["text"] = optimized_map[bt["id"]]

    # ── Letter ──
    letter_vars = {
        "sender_name": person,
        "sender_address": identity.get("address", identity.get("location", "")),
        "sender_email": identity.get("email", ""),
        "sender_phone": identity.get("phone", ""),
        "recipient_name": f"Hiring Manager at {company}",
        "recipient_company": company,
        "recipient_address": body.location,
        "subject": f"Application for {role}",
        "opening": f"Dear Hiring Team at {company},",
        "closing": "Sincerely,",
        "edited_body": body.edited_body,
        "selected_bullets": bullet_texts if not body.edited_body else [],
        "company_name": company,
        "role_title": role,
        "focus_phrase": body.focus_phrase,
        "hook_key": body.hook_key,
        "hook_text": _build_hook_text(body.hook_key, company, role, body.focus_phrase),
        "about_company": f"at {company}",
    }
    slug = _slugify(f"{company}-{role}", "application")
    letter_info = _create_unique(f"tailored_{slug}", "scrlttr2-letter", letter_vars)

    # ── CV, in the variant that matches where it's going ──
    ats = body.channel != "email"
    # Use user-selected template if provided, else default per channel
    cv_template = body.cv_template or ("ats-cv" if ats else "optimized-cv")

    role_groups = _group_bullets_by_role(facts, body.selected_bullet_ids)
    for rg in role_groups:
        for b in rg["bullets"]:
            if b["id"] in optimized_map:
                b["text"] = optimized_map[b["id"]]

    matched_skills, other_skills = _split_skills(
        facts, role_groups,
        jd_text=body.job_ad_text,
        matched_phrases=body.matched_phrases,
    )
    cv_vars = {
        "facts": facts,
        "role_groups": role_groups,
        "selected_bullets": bullet_texts,
        "matched_skills": matched_skills,
        "other_skills": other_skills,
        "language_rows": _language_rows(facts),
    }
    cv_info = _create_unique(f"cv_{slug}", cv_template, cv_vars)

    # ── Compile both ──
    results = {}
    for key, info in (("letter", letter_info), ("cv", cv_info)):
        try:
            r = await compile_doc(info["path"])
            results[key] = {
                "success": r.success,
                "errors": [{"line": e.line, "message": e.message} for e in r.errors[:5]],
            }
        except Exception as e:
            logger.error(f"Compile failed for {info['path']}: {e}")
            results[key] = {"success": False, "errors": [{"line": None, "message": str(e)}]}

    log_application(
        company=company,
        role=role,
        location=body.location,
        letter_path=letter_info["path"],
        cv_path=cv_info["path"],
        matched_count=body.matched_count,
        unmatched_count=len(body.unmatched),
        unmatched_list="; ".join(body.unmatched),
        notes=body.notes,
    )

    return {
        "created": True,
        "channel": "portal" if ats else "email",
        "cv_variant": "ATS-safe (single column)" if ats else "Designed (two column)",
        "letter": {
            "doc_path": letter_info["path"],
            "url": f"/api/pdf/{letter_info['path']}",
            "filename": _pdf_filename(person, "CoverLetter", company),
            **results["letter"],
        },
        "cv": {
            "doc_path": cv_info["path"],
            "url": f"/api/pdf/{cv_info['path']}",
            "filename": _pdf_filename(person, "CV", company),
            **results["cv"],
        },
    }


# Bar length comes from how well the candidate knows a skill, not from whether
# this particular JD happens to mention it. JD relevance drives ordering and
# inclusion instead — see _split_skills.
TIER_LEVEL = {"expert": 90, "proficient": 70, "familiar": 45}

# fortysecondscv's sidebar does not reflow onto page 2, so past roughly ten
# bars the list runs off the bottom of the page.
SIDEBAR_SKILL_LIMIT = 10

# facts.yaml groups related tools into one string ("DOORS - Polarion - XCP").
# As a single bar that both overflows the sidebar and gives five tools one
# meaningless rating, so split them back apart. Requires spaces around the
# dash, which leaves "ISO 26262 ASIL-B" and "MIL/SIL/HIL" intact.
_COMPOUND_SEP = re.compile(r"\s+-\s+")


def _norm(text: str) -> str:
    """Strip separators and case so 'ISO 26262 ASIL-B' compares against 'iso26262'."""
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _mentions(haystack: str, needle: str) -> bool:
    """Whether needle appears in haystack as a whole token.

    Plain substring matching would let 'C#' hit inside 'C#-style' and 'Java'
    inside 'JavaScript'. Guarding on alphanumerics rather than using \\b keeps
    skills ending in punctuation ('C#', 'MATLAB/Simulink') matchable.
    """
    if not needle or not haystack:
        return False
    pattern = r"(?<![A-Za-z0-9])" + re.escape(needle) + r"(?![A-Za-z0-9])"
    return re.search(pattern, haystack, re.IGNORECASE) is not None


def _split_skills(
    facts: dict,
    role_groups: list[dict],
    jd_text: str = "",
    matched_phrases: list[str] | None = None,
    limit: int = SIDEBAR_SKILL_LIMIT,
) -> tuple[list[dict], list[dict]]:
    """Order the skill list by relevance to this job ad.

    Returns (matched, other) as [{"name", "level"}]. `matched` is what the JD
    evidences, capped at `limit` so the sidebar cannot overflow the page.

    Matching against bullet tags alone was not enough: a German-language ad
    never matches English tags, so every application silently fell through to
    the expert-skills fallback and the CV was not tailored at all. The job ad
    text and the requirement phrases the LLM already matched are both checked.
    """
    # Two different matching problems. Ad prose is natural language, so a skill
    # counts only if its full name appears as a token. Bullet tags are short
    # slugs ('autosar', 'iso26262') that must match a longer skill name
    # ('AUTOSAR Classic', 'ISO 26262 ASIL-B'), so those compare both directions
    # with separators stripped.
    prose = "\n".join([jd_text or ""] + list(matched_phrases or []))

    tags: set[str] = set()
    for rg in role_groups:
        if not rg.get("tailored"):
            continue
        for b in rg["bullets"]:
            for t in b.get("tags", []) or []:
                norm = _norm(str(t))
                if norm:
                    tags.add(norm)

    def _tag_hit(name: str) -> bool:
        sn = _norm(name)
        if not sn:
            return False
        for t in tags:
            if t == sn:
                return True
            # Length floor stops 'C#' (normalising to 'c') matching 'canoe'.
            if len(t) >= 3 and t in sn:
                return True
            if len(sn) >= 3 and sn in t:
                return True
        return False

    seen: set[str] = set()
    skills: list[dict] = []
    for tier in ("expert", "proficient", "familiar"):
        for entry in facts.get("skills", {}).get(tier, []) or []:
            if not isinstance(entry, str):
                continue
            for name in _COMPOUND_SEP.split(entry):
                name = name.strip()
                if not name or name.lower() in seen:
                    continue
                seen.add(name.lower())
                skills.append({"name": name, "level": TIER_LEVEL.get(tier, 45)})

    matched = [
        s for s in skills
        if _mentions(prose, s["name"]) or _tag_hit(s["name"])
    ]
    if not matched:
        # Nothing in the ad lines up by name — lead with strongest skills so the
        # sidebar is still ordered sensibly rather than alphabetical.
        logger.info("No JD-relevant skills matched; falling back to top skills by tier")
        matched = [s for s in skills if s["level"] >= TIER_LEVEL["expert"]]

    def _rank(s: dict) -> tuple[int, str]:
        return (-s["level"], s["name"].lower())

    matched.sort(key=_rank)
    matched = matched[:limit]

    matched_names = {s["name"] for s in matched}
    other = sorted((s for s in skills if s["name"] not in matched_names), key=_rank)
    return matched, other


# ── Language rendering ─────────────────────────────────────────────────────────
#
# The sidebar previously hardcoded an if/elif on 'English'/'German', which
# silently dropped every other language and ignored the level in facts.yaml.

_FLAG_CODES = {
    "english": "GB", "german": "DE", "deutsch": "DE", "french": "FR",
    "français": "FR", "chinese": "CN", "mandarin": "CN", "spanish": "ES",
    "italian": "IT", "portuguese": "PT", "dutch": "NL", "polish": "PL",
    "swedish": "SE", "turkish": "TR", "hindi": "IN", "malayalam": "IN",
    "arabic": "SA", "russian": "RU", "japanese": "JP",
}

_CEFR_DOTS = {"a1": 1, "a2": 2, "b1": 3, "b2": 4, "c1": 5, "c2": 5}

# Ordered: the first substring found wins, so 'full professional' resolves
# before the looser 'professional'.
_LEVEL_DOTS = [
    ("native", 5), ("mother", 5), ("bilingual", 5), ("fluent", 5),
    ("full professional", 5), ("professional", 5),
    ("advanced", 4), ("business", 4),
    ("intermediate", 3), ("conversational", 3),
    ("elementary", 2), ("basic", 2), ("beginner", 1),
]

_CEFR_RE = re.compile(r"(?<![A-Za-z0-9])([ABC][12])(?![A-Za-z0-9])", re.IGNORECASE)


def _available_flags() -> set[str]:
    """Flag codes shipped by every template that has a flags folder.

    Intersecting rather than scanning one template keeps the sidebar from
    referencing a PNG that the selected template happens not to ship.
    """
    dirs = list(TEMPLATES.glob("*/pics/flags")) if TEMPLATES.exists() else []
    sets = [{p.stem.upper() for p in d.glob("*.png")} for d in dirs]
    return set.intersection(*sets) if sets else set()


def _language_dots(level: str) -> int:
    """Map a free-text proficiency ('B1 (BAMF Certified)', 'Professional') to 1-5."""
    text = (level or "").lower()
    m = _CEFR_RE.search(text)
    if m:
        return _CEFR_DOTS.get(m.group(1).lower(), 3)
    for word, dots in _LEVEL_DOTS:
        if word in text:
            return dots
    return 3


def _language_rows(facts: dict) -> list[dict]:
    """Build sidebar-ready language entries for any language in facts.yaml."""
    flags = _available_flags()
    rows = []
    for entry in facts.get("languages", []) or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("lang", "")).strip()
        if not name:
            continue
        code = _FLAG_CODES.get(name.lower(), "")
        rows.append({
            "name": name,
            "level": str(entry.get("level", "")).strip(),
            "dots": _language_dots(entry.get("level", "")),
            "flag": code if code in flags else "",
        })
    return rows


def _get_bullet_texts(facts: dict, bullet_ids: list[str]) -> list[dict]:
    """Look up bullet texts from facts.yaml by ID."""
    result = []
    bullet_map = {}
    for role in facts.get("roles", []):
        for bullet in role.get("bullets", []):
            bid = bullet.get("id", "")
            if bid:
                bullet_map[bid] = {
                    "id": bid,
                    "text": bullet.get("text", ""),
                }
    for bid in bullet_ids:
        if bid in bullet_map:
            result.append(bullet_map[bid])
    return result


# ── Preview / guard check for hand-edited text ──────────────────────────────────

class PreviewCheckRequest(BaseModel):
    assembled_text: str
    job_ad_text: str


@router.post("/preview-check")
async def preview_check(body: PreviewCheckRequest):
    """Run guard rules 5-9 on hand-edited letter text. Returns pass/fail + issues."""
    factbank = load_factbank()
    validation = validate_assembled_text(
        body.assembled_text, body.job_ad_text, factbank,
    )
    return {
        "passed": validation.passed,
        "errors": [
            {"rule": e.rule, "message": e.message, "detail": e.detail}
            for e in validation.errors
        ],
        "warnings": [
            {"rule": w.rule, "message": w.message, "detail": w.detail}
            for w in validation.warnings
        ],
    }


def yaml_dump_facts(facts: dict) -> str:
    """Dump facts to a compact YAML string for the LLM prompt."""
    import yaml as _yaml
    return _yaml.dump(facts, default_flow_style=False, allow_unicode=True, sort_keys=False, width=100)


def _get_bullets_with_context(facts: dict, bullet_ids: list[str]) -> list[dict]:
    """Look up bullet texts with role context (org, title, dates, duration)."""
    result = []
    bullet_map = {}
    for role in facts.get("roles", []):
        for bullet in role.get("bullets", []):
            bid = bullet.get("id", "")
            if bid:
                bullet_map[bid] = {
                    "id": bid,
                    "text": bullet.get("text", ""),
                    "tags": bullet.get("tags", []),
                    "role_title": role.get("title", ""),
                    "org": role.get("org", ""),
                    "location": role.get("location", ""),
                    "start": role.get("start", ""),
                    "end": role.get("end", ""),
                    "duration": role.get("duration", ""),
                    "dates": f"{role.get('start', '')} – {role.get('end', '')}",
                }
    for bid in bullet_ids:
        if bid in bullet_map:
            result.append(bullet_map[bid])
    return result


def _group_bullets_by_role(facts: dict, bullet_ids: list[str]) -> list[dict]:
    """
    Group selected bullets under their parent role — one entry per ROLE, not per bullet.

    Two deliberate choices:

    1. Role order and within-role bullet order both follow facts.yaml, never the
       order the LLM returned. facts.yaml is reverse-chronological, so the CV is too,
       and the layout is deterministic (spec 8.7 — assembled, never generated).

    2. Every role is emitted, including ones with no selected bullets. A CV that
       silently drops a job creates an unexplained employment gap, which reads far
       worse than an off-topic bullet. Roles with no selection fall back to their
       own bullets; tailoring shows up as which bullets lead, not which jobs vanish.
    """
    selected = set(bullet_ids)
    roles_out: list[dict] = []

    for role in facts.get("roles", []):
        role_bullets = role.get("bullets", []) or []
        picked = [b for b in role_bullets if b.get("id") in selected]
        shown = picked if picked else role_bullets

        if not shown:
            continue

        roles_out.append({
            "role_title": role.get("title", ""),
            "org": role.get("org", ""),
            "location": role.get("location", ""),
            "start": role.get("start", ""),
            "end": role.get("end", ""),
            "duration": role.get("duration", ""),
            "dates": f"{role.get('start', '')} – {role.get('end', '')}",
            "tailored": bool(picked),
            "bullets": [
                {"id": b.get("id", ""), "text": b.get("text", ""), "tags": b.get("tags", [])}
                for b in shown
            ],
        })

    return roles_out


@router.post("/optimize-cv")
async def optimize_cv(body: OptimizeCvRequest):
    """Assemble an optimized CV from selected bullet IDs."""
    facts = load_facts()
    if not facts:
        raise HTTPException(400, "facts.yaml not found")

    bullet_ids = body.selected_bullet_ids
    optimized_map = {o["id"]: o["text"] for o in body.optimized_bullets if "id" in o and "text" in o}

    # Get bullets with full role context
    bullets = _get_bullets_with_context(facts, bullet_ids)
    if not bullets:
        raise HTTPException(400, "No bullets found for provided IDs")

    # Apply optimized text
    for b in bullets:
        if b["id"] in optimized_map:
            b["text"] = optimized_map[b["id"]]

    # Group into one entry per role so each company gets a single header block
    role_groups = _group_bullets_by_role(facts, bullet_ids)
    for rg in role_groups:
        for b in rg["bullets"]:
            if b["id"] in optimized_map:
                b["text"] = optimized_map[b["id"]]

    matched_skills, other_skills = _split_skills(facts, role_groups)

    # Build template variables
    template_vars = {
        "facts": facts,
        "selected_bullets": bullets,      # flat list, kept for compatibility
        "role_groups": role_groups,       # one entry per role — what the template renders
        "matched_skills": matched_skills,
        "other_skills": other_skills,
        "language_rows": _language_rows(facts),
    }

    # Create document (handles template rendering internally)
    slug = "optimized-cv"
    for attempt in range(1, 100):
        try:
            doc_info = create_document(slug, "optimized-cv", template_vars)
            break
        except FileExistsError:
            slug = f"optimized-cv-{attempt}"
    else:
        raise HTTPException(500, "Could not create document")

    # Update latest application with CV path
    update_latest_cv(doc_info["path"])

    return {
        "created": True,
        "doc_path": doc_info["path"],
        "name": doc_info["name"],
    }


# ── Phase 4: AI template mapping ──────────────────────────────────────────────

MAP_TEMPLATE_PROMPT = """
You are a LaTeX-to-Jinja adapter. Given a raw LaTeX CV/resume template, your job is to
produce a Jinja2 `.j2` file that renders the template from the canonical content shape below.

== CANONICAL CONTENT SHAPE ==

Every template receives a `facts` dict with these fields:

facts.identity:
  .name, .title, .email, .phone, .location, .address, .linkedin, .github,
  .birthdate, .nationality, .work_authorisation, .about, .photo

facts.roles: list of {
  .org, .title, .location, .start, .end, .duration, .dates,
  .tools (list of str), .tailored (bool),
  .bullets: list of { .id, .text, .tags (list of str) }
}

facts.skills: { .expert: [str], .proficient: [str], .familiar: [str] }
facts.education: list of { .degree, .institution, .location, .years, .focus }
facts.languages: list of { .lang, .level }
facts.awards: list of { .year, .title, .org, .description }
facts.hobbies: list of str
facts.contacts: list of { .icon, .text }

== JINJA2 SYNTAX ==

Use these delimiters (NOT standard {{ }}):
  Variable: \\VAR{ facts.identity.name | tex_escape }
  Block:    \\BLOCK{ for role in facts.roles } ... \\BLOCK{ endfor }
  Comment:  \\#{ this is a comment }

The `tex_escape` filter must be applied to EVERY value from facts. Always filter.

== RULES ==

1. Identify every data-bearing command in the template (\\cvname, \\cvitem, \\section, \\textbf, etc.)
2. Map each one to the closest canonical field above.
3. Replace raw LaTeX data with \\VAR{} references, wrapped in \\BLOCK{} loops where needed.
4. Preserve ALL preamble, packages, styling, and non-data LaTeX code unchanged.
5. NEVER invent facts. If a template field has no matching canonical data, use an empty \\VAR{} or a comment.
6. Output ONLY the complete .j2 file in a ```tex code block. No explanation outside the block.
7. Use \\VAR{ ... | tex_escape } for EVERY value. Do NOT use bare \\VAR{}.
""".strip()


class MapTemplateRequest(BaseModel):
    raw_tex: str
    template_name: str
    layout: str = "designed"       # "ats" or "designed"
    provider: str | None = None
    model: str | None = None


@router.post("/map-template")
async def map_template(body: MapTemplateRequest):
    """AI reads an unfamiliar .tex CV template and produces a .j2 adapter."""
    raw_tex = body.raw_tex.strip()
    if not raw_tex:
        raise HTTPException(400, "Template text is required")
    if len(raw_tex) < 200:
        raise HTTPException(400, "Template too short — paste the full .tex file")

    template_name = body.template_name.strip().lower().replace(" ", "-")[:40]
    if not template_name:
        raise HTTPException(400, "Template name is required")

    facts = load_facts()
    if not facts:
        raise HTTPException(400, "facts.yaml not found — the adapter needs sample data to validate against")

    # Build the LLM prompt
    messages = [
        {"role": "system", "content": MAP_TEMPLATE_PROMPT},
        {"role": "user", "content": f"Here is a sample of the canonical data shape (use these field paths):\n\n```json\n{json.dumps({k: type(v).__name__ for k, v in facts.items()}, indent=2)}\n```"},
        {"role": "assistant", "content": "I understand the data shape. Send me the LaTeX template and I'll produce the .j2 adapter."},
        {"role": "user", "content": f"Convert this LaTeX template to a .j2 adapter:\n\n```tex\n{raw_tex[:15000]}\n```"},
    ]

    async def event_generator():
        llm = None
        try:
            yield f"event: status\ndata: {json.dumps({'step': 'calling_llm', 'message': 'Asking the AI to map template macros to your data...'})}\n\n"

            llm = get_provider(body.provider, body.model)
            full = ""
            async for token in llm.chat(messages, stream=True):
                full += token
                yield f"data: {json.dumps({'token': token})}\n\n"

            # Extract .j2 from response
            tex_match = re.search(r"```tex\s*([\s\S]*?)```", full)
            if not tex_match:
                yield f"event: error\ndata: {json.dumps({'error': 'AI did not produce a code block — try again or simplify the template.'})}\n\n"
                return

            j2_content = tex_match.group(1).strip()

            # ── Guard validation: render the .j2 against facts ──
            yield f"event: status\ndata: {json.dumps({'step': 'validating', 'message': 'Rendering adapter against your fact bank to check for hallucinations...'})}\n\n"

            # Save as a temporary template to validate
            tpl_dir = Path(__file__).parent.parent / "workspace" / "templates" / template_name
            tpl_dir.mkdir(parents=True, exist_ok=True)
            (tpl_dir / "main.tex.j2").write_text(j2_content, encoding="utf-8")
            (tpl_dir / "template.json").write_text(json.dumps({
                "name": body.template_name,
                "kind": "cv",
                "layout": body.layout,
                "icon": "🤖",
                "colour": "#89b4fa",
                "description": f"AI-mapped template from user-provided .tex",
                "requires": ["identity", "roles"],
                "variables": {},
            }), encoding="utf-8")

            # Render against real facts
            try:
                rendered = render_template(template_name, {"facts": facts})
            except Exception as e:
                yield f"event: error\ndata: {json.dumps({'error': f'Adapter rendering failed: {str(e)[:200]}'})}\n\n"
                return

            # Guard check on rendered output
            factbank = load_factbank()
            validation = validate_tailor_response(
                {"selected_bullet_ids": [], "matched_requirements": [],
                 "focus_phrase": "test", "hook_key": "exact_match"},
                "", factbank, assembled_text=rendered,
            )

            guard_errors = [{"rule": e.rule, "message": e.message, "detail": e.detail} for e in validation.errors]
            guard_warnings = [{"rule": w.rule, "message": w.message} for w in validation.warnings]

            yield f"event: done\ndata: {json.dumps({
                'success': validation.passed,
                'template_id': template_name,
                'j2_content': j2_content,
                'rendered_lines': len(rendered.splitlines()),
                'guard_errors': guard_errors,
                'guard_warnings': guard_warnings,
                'message': 'Adapter saved and validated.' if validation.passed else 'Adapter has issues — review errors above.',
            })}\n\n"

        except ValueError as e:
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
        except Exception as e:
            logger.error(f"Template mapping error: {e}")
            yield f"event: error\ndata: {json.dumps({'error': f'Mapping failed: {e}'})}\n\n"
        finally:
            if llm is not None:
                try:
                    await llm.close()
                except Exception:
                    pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
