# ── Phase 6: Content mode — JD parsing + fact-matching + letter assembly ──

import json
import logging
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.compile import compile_doc
from app.docs import create_document, load_facts, render_template, tex_escape
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
        raise HTTPException(400, "facts.yaml not found or empty")

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
    cv_template = "ats-cv" if ats else "optimized-cv"

    role_groups = _group_bullets_by_role(facts, body.selected_bullet_ids)
    for rg in role_groups:
        for b in rg["bullets"]:
            if b["id"] in optimized_map:
                b["text"] = optimized_map[b["id"]]

    matched_skills, other_skills = _split_skills(facts, role_groups)
    cv_vars = {
        "facts": facts,
        "role_groups": role_groups,
        "selected_bullets": bullet_texts,
        "matched_skills": matched_skills,
        "other_skills": other_skills,
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


def _split_skills(facts: dict, role_groups: list[dict]) -> tuple[list[str], list[str]]:
    """Split the skill list into ones this application evidences and the rest."""
    seen_tags: set[str] = set()
    for rg in role_groups:
        if not rg.get("tailored"):
            continue
        for b in rg["bullets"]:
            for tag in b.get("tags", []) or []:
                seen_tags.add(str(tag).lower())

    all_skills: list[str] = []
    for tier in ("expert", "proficient", "familiar"):
        for s in facts.get("skills", {}).get(tier, []) or []:
            if isinstance(s, str):
                all_skills.append(s)

    matched = {
        skill for skill in all_skills
        for tag in seen_tags
        if tag in skill.lower() or skill.lower() in tag
    }
    if not matched:
        matched = set(facts.get("skills", {}).get("expert", [])[:8])

    return sorted(matched), sorted(s for s in all_skills if s not in matched)


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

    # Determine matched skills from bullet tags + role tools
    matched_skills: set[str] = set()
    seen_tags: set[str] = set()
    for b in bullets:
        for tag in b.get("tags", []):
            seen_tags.add(tag.lower())

    all_skills = []
    for tier in ("expert", "proficient", "familiar"):
        for s in facts.get("skills", {}).get(tier, []):
            if isinstance(s, str):
                all_skills.append(s)

    # Simple tag-to-skill matching: fuzzy
    for skill in all_skills:
        skill_lower = skill.lower()
        for tag in seen_tags:
            if tag in skill_lower or skill_lower in tag:
                matched_skills.add(skill)
                break

    # Fallback: include all expert skills if no matches found
    if not matched_skills:
        for s in facts.get("skills", {}).get("expert", [])[:8]:
            if isinstance(s, str):
                matched_skills.add(s)

    other_skills = [s for s in all_skills if s not in matched_skills]

    # Build template variables
    template_vars = {
        "facts": facts,
        "selected_bullets": bullets,      # flat list, kept for compatibility
        "role_groups": role_groups,       # one entry per role — what the template renders
        "matched_skills": sorted(matched_skills),
        "other_skills": sorted(other_skills),
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
