# ── Phase 6: Content mode — JD parsing + fact-matching + letter assembly ──

import json
import logging
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.compile import compile_doc
from app.docs import TEMPLATES, create_document, list_templates, load_facts, render_template, tex_escape
from app.guard.factbank import load_factbank
from app.guard.validator import validate_assembled_text, validate_tailor_response
from app.llm.provider import get_provider
from app.paths import PROMPTS_DIR, WORKSPACE as PATHS_WORKSPACE
from app.tracker import log_application, update_latest_cv
from app.i18n import SUPPORTED as _LANGUAGES, get_language

logger = logging.getLogger("latex_studio.content")
router = APIRouter(prefix="/api/content", tags=["content"])

CONTENT_PROMPT_PATH = PROMPTS_DIR / "content_mode.md"
_prompt_cache: str | None = None


def _load_content_prompt() -> str:
    global _prompt_cache
    if _prompt_cache is None:
        if CONTENT_PROMPT_PATH.exists():
            _prompt_cache = CONTENT_PROMPT_PATH.read_text(encoding="utf-8")
        else:
            _prompt_cache = "You are a career document assistant."
    return _prompt_cache


HOOKS_PATH = PATHS_WORKSPACE / "hooks.yaml"
CHROME_PATH = PATHS_WORKSPACE / "i18n" / "letter_chrome.yaml"
LABELS_PATH = PATHS_WORKSPACE / "i18n" / "labels.yaml"


# ── Template resolution ────────────────────────────────────────────────────────

def _resolve_template(template_id: str, want_kind: str) -> str:
    """Validate and canonicalise a user-facing template id.

    Returns the template id unchanged on success.
    Raises 400 for unknown ids or a kind mismatch.
    """
    if not template_id or "/" in template_id or "\\" in template_id or template_id.startswith("."):
        raise HTTPException(400, f"Invalid template id: '{template_id}'")

    all_templates = {t["id"]: t for t in list_templates()}
    info = all_templates.get(template_id)
    if not info:
        known = ", ".join(sorted(all_templates.keys()))
        raise HTTPException(400, f"Unknown template '{template_id}'. Known: {known}")
    if not info.get("has_template"):
        raise HTTPException(400, f"Template '{template_id}' has no renderable source")

    kind = info.get("kind", "cv")
    if want_kind == "letter" and kind != "letter":
        raise HTTPException(
            400,
            f"'{template_id}' is a {kind} template, not a letter template. "
            f"Letter templates: {', '.join(k for k, v in all_templates.items() if v.get('kind') == 'letter')}",
        )
    if want_kind == "cv" and kind != "cv":
        raise HTTPException(
            400,
            f"'{template_id}' is a {kind} template, not a CV template.",
        )

    return template_id


# ── Letter chrome (per-language salutation, subject, closing) ───────────────────

def _load_letter_chrome() -> dict:
    if not CHROME_PATH.exists():
        return {}
    import yaml as _yaml
    return _yaml.safe_load(CHROME_PATH.read_text(encoding="utf-8")) or {}


def _load_labels() -> dict:
    if not LABELS_PATH.exists():
        return {}
    import yaml as _yaml
    return _yaml.safe_load(LABELS_PATH.read_text(encoding="utf-8")) or {}


def _letter_chrome(lang_code: str) -> dict:
    """Return the chrome dict for a language, falling back to English."""
    chrome_all = _load_letter_chrome()
    return chrome_all.get(lang_code) or chrome_all.get("en", {})


def _letter_vars(
    company: str,
    role: str,
    location: str,
    focus_phrase: str,
    hook_key: str,
    facts: dict,
    bullet_texts: list[dict],
    edited_body: str | None = None,
    language: str = "en",
) -> dict:
    """Build template variables for a cover letter. Used by /tailor and /generate."""
    identity = facts.get("identity", {})
    chrome = _letter_chrome(language)
    labels = _load_labels()

    subject = chrome.get("subject", "Application for {role_title}").replace(
        "{role_title}", role
    )
    opening = chrome.get("opening", "Dear Hiring Team at {company_name},").replace(
        "{company_name}", company
    )
    closing = chrome.get("closing", "Sincerely,")
    closing_sentence = chrome.get("closing_sentence", "")
    if closing_sentence:
        closing_sentence = closing_sentence.replace("{company_name}", company)

    lang_info = get_language(language)
    babel_lang = lang_info.babel if lang_info else "english"

    return {
        "sender_name": identity.get("name", ""),
        "sender_address": identity.get("address", identity.get("location", "")),
        "sender_email": identity.get("email", ""),
        "sender_phone": identity.get("phone", ""),
        "recipient_name": f"Hiring Manager at {company}",
        "recipient_company": company,
        "recipient_address": location,
        "subject": subject,
        "opening": opening,
        "closing": closing,
        "closing_sentence": closing_sentence,
        "edited_body": edited_body,
        "selected_bullets": bullet_texts if not edited_body else [],
        "company_name": company,
        "role_title": role,
        "focus_phrase": focus_phrase,
        "hook_key": hook_key,
        # When a non-English edited_body is supplied the hook was included in the
        # translation and must not be rendered again as a separate paragraph.
        "hook_text": "" if (edited_body and language != "en")
                     else _build_hook_text(hook_key, company, role, focus_phrase, language),
        "about_company": f"at {company}",
        "babel_lang": babel_lang,
        "language": language,
        "L": labels,
    }


def _cv_vars(facts: dict, bullet_ids: list[str], optimized_map: dict,
             job_ad_text: str = "", matched_phrases: list[str] | None = None,
             language: str = "en") -> dict:
    """Build template variables for a CV."""
    role_groups = _group_bullets_by_role(facts, bullet_ids)
    for rg in role_groups:
        for b in rg["bullets"]:
            if b["id"] in optimized_map:
                b["text"] = optimized_map[b["id"]]

    matched_skills, other_skills = _split_skills(
        facts, role_groups,
        jd_text=job_ad_text,
        matched_phrases=matched_phrases,
    )
    labels = _load_labels()
    lang_info = get_language(language)
    babel_lang = lang_info.babel if lang_info else "english"
    return {
        "facts": facts,
        "role_groups": role_groups,
        "selected_bullet_ids": bullet_ids,
        "matched_skills": matched_skills,
        "other_skills": other_skills,
        "language_rows": _language_rows(facts),
        "language": language,
        "babel_lang": babel_lang,
        "L": labels,
    }


def _load_hooks() -> dict:
    """Load the pre-written opening hooks. Not cached — edit hooks.yaml and re-run."""
    if not HOOKS_PATH.exists():
        return {}
    import yaml as _yaml
    return _yaml.safe_load(HOOKS_PATH.read_text(encoding="utf-8")) or {}


def _build_hook_text(hook_key: str, company_name: str, role_title: str, focus_phrase: str, language: str = "en") -> str:
    """
    Render the opening paragraph for a validated hook_key.

    The hook prose is human-authored (workspace/hooks.yaml); the model only selects
    which key applies, and guard rule 4 has already checked the key is in the enum.
    Slot values are LaTeX-escaped before substitution, so the result is already safe
    and must NOT be passed through tex_escape again in the template.

    Hooks are stored flat (compatible with hooks.example.yaml) or per-language.
    Uses replace() rather than format() so braces in hook prose don't blow up.
    """
    hooks = _load_hooks()

    # Try per-language key first, fall back to flat key
    template = ""
    if language != "en":
        per_lang = hooks.get(language, {})
        if isinstance(per_lang, dict):
            template = per_lang.get(hook_key, "")
    if not template:
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
    # The slot values above are escaped, but the AUTHORED prose around them can
    # still contain &, %, $, _, # — escape the full assembled string once.
    return " ".join(tex_escape(template).split())


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

            # Empty response — the LLM streamed zero tokens (common causes:
            # missing/invalid API key, wrong model name, DeepSeek API returning
            # 200 with no content for oversized prompts or quota exhaustion).
            if not full.strip():
                logger.error(f"Content mode: LLM returned empty response "
                             f"(provider={provider or 'default'}, model={model or 'auto'}, "
                             f"facts_size={len(facts_yaml_block)} chars, jd_size={len(job_ad)} chars)")
                yield f"event: error\ndata: {json.dumps({'error': 'The AI returned an empty response. Check your API key in .env, verify the model name, or check provider status.'})}\n\n"
                return

            # Extract JSON from response
            json_match = re.search(r"```json\s*([\s\S]*?)```", full)
            if json_match:
                json_str = json_match.group(1).strip()
            else:
                # Try to find a JSON object {...} in the response
                obj_match = re.search(r"\{[\s\S]*\}", full)
                if obj_match:
                    json_str = obj_match.group(0).strip()
                else:
                    json_str = full.strip()

            try:
                parsed = json.loads(json_str)
            except json.JSONDecodeError as e:
                preview = json_str[:200].replace("\n", "\\n")
                logger.error(f"Content mode: JSON parse failed. json_str_len={len(json_str)}, preview={preview}")
                yield f"event: error\ndata: {json.dumps({'error': f'Failed to parse LLM response as JSON: {e}'})}\n\n"
                return

            # Extract TailorResponse fields from parsed JSON
            tailor_data = {
                "matched_requirements": parsed.get("matched_requirements", []),
                "selected_bullet_ids": _expand_role_ids_to_bullets(
                    facts, parsed.get("selected_bullet_ids", [])
                ),
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

            template_vars = _letter_vars(
                company=company_name, role=role_title, location=location,
                focus_phrase=focus_phrase, hook_key=hook_key,
                facts=facts, bullet_texts=bullet_texts,
            )
            # Add manual template-only fields and the rendered body
            template_vars["selected_bullets"] = bullet_texts  # bodies block expects plain list

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
                'hook_text': template_vars.get('hook_text', ''),
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
    """Everything /tailor returned, plus what the user chose in the Step 3 form."""
    channel: str = "portal"
    cv_template: str = ""
    letter_template: str = ""               # defaults to "scrlttr2-letter"
    documents: list[str] = ["letter", "cv"]  # subset of {"letter", "cv"}
    language: str = "en"
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
    edited_body: str | None = None
    job_ad_text: str = ""
    matched_phrases: list[str] = []
    # {key: translated_text} from /translate-cv. Already guard-checked there;
    # substituted verbatim so /generate keeps no model in the loop.
    translated_cv: dict[str, str] = {}


def _slugify(text: str, fallback: str) -> str:
    # Dash-separated, used for PDF/folder names. Intentionally differs from
    # importer._slugify which uses underscores for YAML fact keys.
    return re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-") or fallback


def _create_unique(base_name: str, template_id: str, variables: dict,
                   origin: str = "manual", language: str = "en",
                   company: str = "", role: str = "", channel: str = "") -> dict:
    """create_document, retrying with a numeric suffix when the folder already exists."""
    name = base_name
    for attempt in range(2, 100):
        try:
            return create_document(name, template_id, variables, origin=origin,
                                   language=language, company=company, role=role, channel=channel)
        except FileExistsError:
            name = f"{base_name}-{attempt}"
    raise HTTPException(500, f"Could not find a free document name for '{base_name}'")


def _pdf_filename(person: str, kind: str, company: str, role: str) -> str:
    """Afeef_Kallanthodan_CoverLetter_Bertrandt_Group__Senior_Embedded_Engineer_2026-08-07.pdf"""
    def clean(s: str) -> str:
        return re.sub(r"[^A-Za-z0-9]+", "_", (s or "").strip()).strip("_")
    from datetime import datetime
    date_str = datetime.now().strftime("%Y-%m-%d")
    prefix = "_".join(p for p in [clean(person) or "Candidate", kind, clean(company)] if p)
    suffix = "_".join(p for p in [clean(role), date_str] if p)
    return f"{prefix}__{suffix}.pdf"


@router.post("/generate")
async def generate_documents(body: GenerateRequest):
    """
    Create the cover letter and/or CV, compile, log the application, and hand back
    download links.

    Controls: documents (subset of {"letter","cv"}), language (ISO 639-1 code),
    cv_template / letter_template (validated against list_templates()).

    This is the only place documents are written. /tailor just analyses.
    """
    # ── Input validation ──
    if not body.documents:
        raise HTTPException(400, "documents list is empty — pick at least one of 'letter' or 'cv'")
    unknown = [d for d in body.documents if d not in ("letter", "cv")]
    if unknown:
        raise HTTPException(400, f"Invalid document kind(s): {', '.join(unknown)}. Must be 'letter' and/or 'cv'")

    lang = get_language(body.language)
    if lang is None:
        codes = ", ".join(l.code for l in _LANGUAGES)
        raise HTTPException(400, f"Unsupported language '{body.language}'. Supported: {codes}")

    facts = load_facts()
    if not facts:
        raise HTTPException(400, "facts.yaml not found or empty")

    identity = facts.get("identity", {})
    person = identity.get("name", "")
    company = body.company_name or "the company"
    role = body.role_title or "this position"
    language = body.language

    bullet_texts = _get_bullet_texts(facts, body.selected_bullet_ids)
    optimized_map = {
        o["id"]: o["text"] for o in body.optimized_bullets if "id" in o and "text" in o
    }
    # Apply optimized text — letter bullets use the same map below
    for bt in bullet_texts:
        if bt["id"] in optimized_map:
            bt["text"] = optimized_map[bt["id"]]

    # ── Write gate: rules 5 & 9 on user-edited or translated body text ──
    if body.edited_body:
        from app.guard.validator import validate_write_gate
        factbank = load_factbank()
        gate = validate_write_gate(body.edited_body, factbank, body.language)
        if not gate.passed:
            raise HTTPException(422, detail={
                "errors": [{"rule": e.rule, "message": e.message, "detail": e.detail}
                           for e in gate.errors],
            })

    slug = _slugify(f"{company}-{role}", "application")

    # ── Build document spec list lazily ──
    # Each spec is a (kind, template_id, folder_name, variables) tuple.
    # The CV block is only built when actually wanted — _group_bullets_by_role +
    # _split_skills is wasted work otherwise.
    specs: list[tuple[str, str, str, dict]] = []

    want_letter = "letter" in body.documents
    want_cv = "cv" in body.documents

    if want_letter:
        lt = body.letter_template or "scrlttr2-letter"
        _resolve_template(lt, "letter")
        letter_vars = _letter_vars(
            company=company, role=role, location=body.location,
            focus_phrase=body.focus_phrase, hook_key=body.hook_key,
            facts=facts, bullet_texts=bullet_texts,
            edited_body=body.edited_body, language=language,
        )
        specs.append(("letter", lt, f"tailored_{slug}", letter_vars))

    if want_cv:
        ats = body.channel != "email"
        ct = body.cv_template or ("ats-cv" if ats else "designed-cv")
        _resolve_template(ct, "cv")
        cv_vars = _cv_vars(
            facts=facts, bullet_ids=body.selected_bullet_ids,
            optimized_map=optimized_map,
            job_ad_text=body.job_ad_text,
            matched_phrases=body.matched_phrases,
            language=language,
        )
        if body.translated_cv:
            from app.cv_translate import apply_cv_strings
            cv_vars = apply_cv_strings(cv_vars, body.translated_cv)
        specs.append(("cv", ct, f"cv_{slug}", cv_vars))

    # ── Create + compile each document ──
    results: dict[str, dict] = {}
    doc_info: dict[str, dict] = {}

    for kind, template_id, folder_name, variables in specs:
        try:
            info = _create_unique(folder_name, template_id, variables, origin="apply",
                                  language=language, company=company, role=role,
                                  channel=body.channel)
        except FileExistsError:
            # _create_unique retries with a suffix — fallback in case it exhausts
            raise HTTPException(500, f"Could not find a free document name for '{folder_name}'")
        doc_info[kind] = info

        try:
            r = await compile_doc(info["path"])
            results[kind] = {
                "success": r.success,
                "errors": [{"line": e.line, "message": e.message} for e in r.errors[:5]],
                "doc_path": info["path"],
                "url": f"/api/pdf/{info['path']}",
                "filename": _pdf_filename(person, "CoverLetter" if kind == "letter" else "CV", company, role),
            }
        except Exception as e:
            logger.error(f"Compile failed for {info['path']}: {e}")
            results[kind] = {
                "success": False,
                "errors": [{"line": None, "message": str(e)}],
                "doc_path": info["path"],
                "url": f"/api/pdf/{info['path']}",
                "filename": _pdf_filename(person, "CoverLetter" if kind == "letter" else "CV", company, role),
            }

    # ── Log the application ──
    letter_path = doc_info.get("letter", {}).get("path", "")
    cv_path = doc_info.get("cv", {}).get("path", "")
    log_application(
        company=company, role=role, location=body.location,
        letter_path=letter_path, cv_path=cv_path,
        matched_count=body.matched_count,
        unmatched_count=len(body.unmatched),
        unmatched_list="; ".join(body.unmatched),
        notes=body.notes,
        language=language,
        cv_template=body.cv_template or ("ats-cv" if body.channel != "email" else "designed-cv"),
        letter_template=body.letter_template or "scrlttr2-letter",
    )

    # ── Response — null keys for skipped documents ──
    ats = body.channel != "email"
    return {
        "created": True,
        "channel": "portal" if ats else "email",
        "cv_variant": "ATS-safe (single column)" if ats else "Designed (two column)",
        "language": language,
        "documents": body.documents,
        "letter": results.get("letter"),
        "cv": results.get("cv"),
    }


# Bar length comes from how well the candidate knows a skill, not from whether
# this particular JD happens to mention it. JD relevance drives ordering and
# inclusion instead — see _split_skills.
TIER_LEVEL = {"expert": 90, "proficient": 70, "familiar": 45}

# fortysecondscv's sidebar does not reflow onto page 2, so past roughly ten
# bars the list runs off the bottom of the page.
SIDEBAR_SKILL_LIMIT = 10


def _sidebar_skill_limit(facts: dict) -> int:
    """How many bars fit alongside whatever else the sidebar is carrying.

    The sidebar is a fixed-height textblock: it neither reflows to page 2 nor
    warns on overrun, it just drops content off the bottom edge, so the budget has
    to be reserved up front. Measured by compiling this layout — ten bars fit on
    their own, a profile photo costs about two, and a hobbies list about three
    (its entries wrap when the text is long, as 'AI Enthusiast / Implementing
    local AI' does).
    """
    limit = SIDEBAR_SKILL_LIMIT
    if facts.get("identity", {}).get("photo"):
        limit -= 2
    if facts.get("hobbies"):
        limit -= 3
    return max(3, limit)

# facts.yaml groups related tools into one string ("DOORS - Polarion - XCP").
# As a single bar that both overflows the sidebar and gives five tools one
# meaningless rating, so split them back apart. Requires spaces around the
# dash, which leaves "ISO 26262 ASIL-B" and "MIL/SIL/HIL" intact.
_COMPOUND_SEP = re.compile(r"\s+-\s+")


def _norm(text: str) -> str:
    """Strip separators and case so 'ISO 26262 ASIL-B' compares against 'iso26262'."""
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


# Words too generic to imply that one skill covers another. Without these,
# 'Embedded Coder toolchain evaluation' is swallowed by 'Embedded C / AUTOSAR /
# MISRA' on the shared word 'embedded' alone.
_GENERIC_WORDS = {
    "embedded", "software", "hardware", "test", "tests", "testing",
    "automation", "automated", "requirements", "design", "system", "systems",
    "tool", "tools", "toolchain", "development", "engineering", "management",
    "analysis", "based", "and", "the", "for", "with",
}


def _tokens(text: str) -> set[str]:
    """Significant lowercase words. Drops 1-2 char noise so the 'C' in
    'Embedded C / AUTOSAR' cannot collide with every other skill."""
    return {t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if len(t) >= 3}


def _distinctive(text: str) -> set[str]:
    """Tokens that actually identify a skill. Falls back to the full token set for
    names built entirely from generic words ('Embedded C'), which would otherwise
    compare as empty and never match anything."""
    toks = _tokens(text)
    return (toks - _GENERIC_WORDS) or toks


def _curated_bars(facts: dict) -> list[dict]:
    """Hand-authored sidebar bars from facts.yaml, in the order written.

    These deliberately bypass _COMPOUND_SEP: a curated name like
    'MBD - Matlab/Simulink/m-Scripting' is one bar by intent, and splitting it
    would undo exactly the grouping the author chose.
    """
    bars = []
    for entry in facts.get("skill_bars", []) or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        if not name:
            continue
        try:
            level = int(entry.get("level", 70))
        except (TypeError, ValueError):
            level = 70
        bars.append({"name": name, "level": max(0, min(100, level))})
    return bars


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
    limit: int | None = None,
) -> tuple[list[dict], list[dict]]:
    """Order the skill list by relevance to this job ad.

    Returns (matched, other) as [{"name", "level"}]. `matched` is what the JD
    evidences, capped at `limit` so the sidebar cannot overflow the page.

    Matching against bullet tags alone was not enough: a German-language ad
    never matches English tags, so every application silently fell through to
    the expert-skills fallback and the CV was not tailored at all. The job ad
    text and the requirement phrases the LLM already matched are both checked.
    """
    if limit is None:
        limit = _sidebar_skill_limit(facts)

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
            # Retained roles now carry their unselected bullets too, so harvesting
            # every tag here would drown the JD signal in unrelated ones.
            if not b.get("selected", True):
                continue
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

    curated = _curated_bars(facts)
    if not curated:
        matched = matched[:limit]
        matched_names = {s["name"] for s in matched}
        other = sorted((s for s in skills if s["name"] not in matched_names), key=_rank)
        return matched, other

    # Curated bars lead, in the order the author wrote them, at their stated levels.
    # A tier skill is dropped when a curated bar already speaks for it — compared on
    # shared words, since 'AUTOSAR Classic' is covered by 'Embedded C / AUTOSAR /
    # MISRA' without either string containing the other.
    curated_sig = [(_distinctive(b["name"]), _tokens(b["name"])) for b in curated]

    def _covered(name: str) -> bool:
        sig, toks = _distinctive(name), _tokens(name)
        for bar_sig, bar_toks in curated_sig:
            if sig & bar_sig:
                return True
            # Names made only of generic words ('Embedded C') have no distinctive
            # tokens to match on, so accept them when the bar spells them out in full.
            if toks and toks <= bar_toks:
                return True
        return False

    extras = [s for s in matched if not _covered(s["name"])]
    bars = (curated + extras)[:limit]

    bar_names = {b["name"] for b in bars}
    other = sorted(
        (s for s in skills if s["name"] not in bar_names and not _covered(s["name"])),
        key=_rank,
    )
    return bars, other


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


def _expand_role_ids_to_bullets(facts: dict, ids: list[str]) -> list[str]:
    """
    Expand any role-level IDs in `ids` to their constituent bullet IDs.
    Proper bullet IDs pass through unchanged. Unknown IDs are silently dropped.

    The LLM sometimes returns a role `id` (e.g. 'koosys') instead of individual
    bullet IDs (e.g. 'koosys_foc'). Both appear in facts.yaml so they pass Rule 2,
    but _get_bullet_texts only resolves bullet-level IDs — leading to an empty
    letter body. Expanding here fixes that at the source, before any validation.
    """
    all_bullet_ids: set[str] = set()
    role_to_bullets: dict[str, list[str]] = {}

    for role in facts.get("roles", []):
        role_id = role.get("id", "")
        bids = [b["id"] for b in role.get("bullets", []) if b.get("id")]
        if role_id:
            role_to_bullets[role_id] = bids
        all_bullet_ids.update(bids)

    result: list[str] = []
    seen: set[str] = set()
    for fid in ids:
        if fid in all_bullet_ids:
            if fid not in seen:
                result.append(fid)
                seen.add(fid)
        elif fid in role_to_bullets:
            for bid in role_to_bullets[fid]:
                if bid not in seen:
                    result.append(bid)
                    seen.add(bid)
    return result


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
    language: str = "en"


@router.post("/preview-check")
async def preview_check(body: PreviewCheckRequest):
    """Run guard rules 5-9 on hand-edited letter text. Returns pass/fail + issues."""
    factbank = load_factbank()
    validation = validate_assembled_text(
        body.assembled_text, body.job_ad_text, factbank, language=body.language,
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

    3. Every bullet of a retained role is shown, JD-relevant ones first. Showing only
       the selected two or three left the page half empty and read thinner than the
       hand-written CV. Ordering stays deterministic: selection is a set, and
       facts.yaml order is preserved within each group, so the output is still
       assembled rather than generated.

    Each bullet carries `selected` so callers can tell the tailored ones apart —
    _split_skills relies on it to harvest tags only from bullets the JD actually
    matched, which would otherwise be diluted by the unselected ones.
    """
    selected = set(bullet_ids)
    roles_out: list[dict] = []

    for role in facts.get("roles", []):
        role_bullets = role.get("bullets", []) or []
        picked = [b for b in role_bullets if b.get("id") in selected]
        rest = [b for b in role_bullets if b.get("id") not in selected]
        shown = picked + rest

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
            "tools": role.get("tools", []) or [],
            "tailored": bool(picked),
            "bullets": [
                {
                    "id": b.get("id", ""),
                    "text": b.get("text", ""),
                    "tags": b.get("tags", []),
                    "selected": b.get("id") in selected,
                }
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
    slug = "custom-cv"
    for attempt in range(1, 100):
        try:
            doc_info = create_document(slug, "ats-cv", template_vars)
            break
        except FileExistsError:
            slug = f"custom-cv-{attempt}"
    else:
        raise HTTPException(500, "Could not create document")

    # Update latest application with CV path
    update_latest_cv(doc_info["path"])

    return {
        "created": True,
        "doc_path": doc_info["path"],
        "name": doc_info["name"],
    }


# ── Translate assembled letter body ──────────────────────────────────────────

TRANSLATE_SYSTEM_PROMPT = (
    "You are a professional translator. Translate the following cover letter body "
    "to {target_language}.\n\n"
    "RULES:\n"
    "1. Preserve ALL numbers, percentages, dates, and proper nouns exactly as written.\n"
    "2. Preserve ALL LaTeX commands and formatting — never translate inside \\textbf{{}}, "
    "\\emph{{}}, \\href{{}}, or any curly-brace argument.\n"
    "3. Do not add any new claims, certifications, or qualifications.\n"
    "4. Output only the translated text — no preamble, no explanations."
)


class TranslateRequest(BaseModel):
    text: str
    language: str
    provider: str | None = None
    model: str | None = None
    job_ad_text: str = ""


@router.post("/translate")
async def translate_text(body: TranslateRequest):
    """Translate the assembled letter body to a target language."""
    lang = get_language(body.language)
    if lang is None:
        codes = ", ".join(l.code for l in _LANGUAGES)
        raise HTTPException(400, f"Unsupported language '{body.language}'. Supported: {codes}")
    if body.language == "en":
        return {"translated": body.text, "language": "en", "passed": True, "errors": [], "warnings": []}

    text = body.text.strip()
    if not text:
        raise HTTPException(400, "No text provided to translate")

    facts = load_facts()
    factbank = load_factbank()

    llm = get_provider(body.provider, body.model)
    target_name = lang.english_name
    system = TRANSLATE_SYSTEM_PROMPT.replace("{target_language}", target_name)

    full = ""
    try:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ]
        async for token in llm.chat(messages, stream=True):
            full += token
    except Exception as e:
        raise HTTPException(502, f"Translation provider error: {e}")
    finally:
        try:
            await llm.close()
        except Exception:
            pass

    translated = full.strip()

    # Verify preservation: numbers, entities, banned claims, certifications
    from app.translate import check_translation
    check = check_translation(text, translated, factbank)
    # Run rules 5 and 9 on the translated output
    from app.guard.validator import validate_write_gate
    gate = validate_write_gate(translated, factbank, body.language)

    all_errors = check.get("errors", []) + [
        {"rule": e.rule, "message": e.message, "detail": e.detail}
        for e in gate.errors
    ]

    return {
        "translated": translated,
        "language": body.language,
        "passed": len(all_errors) == 0,
        "errors": all_errors,
        "warnings": check.get("warnings", []) + [
            {"rule": w.rule, "message": w.message, "detail": w.detail}
            for w in gate.warnings
        ],
    }


# ── Translate CV content ─────────────────────────────────────────────────────
#
# The letter round-trips as prose; a CV cannot. It is a structure of short
# strings, and translating it as one blob would lose which bullet belongs to
# which role. So it goes over as a flat {key: text} JSON map and comes back the
# same shape — see app/cv_translate.py for the key scheme.
#
# This endpoint holds the model. /generate stays model-free: it receives the
# finished map and only substitutes, which keeps "the only place documents are
# written has no LLM in the loop" true.

CV_TRANSLATE_SYSTEM_PROMPT = (
    "You are a professional CV translator. You receive a JSON object mapping opaque keys "
    "to short English CV strings. Translate ONLY the values into {target_language} and "
    "return a JSON object with EXACTLY the same keys.\n\n"
    "RULES:\n"
    "1. Return ONLY valid JSON. No markdown fence, no commentary, no preamble.\n"
    "2. Keep every key byte-for-byte as given. Never add, drop, merge, or reorder keys.\n"
    "3. NEVER translate proper nouns. Copy them through verbatim: employer and company "
    "names, university names, city and country names, people's names, product and tool "
    "names, programming languages, and technical standards with their identifiers "
    "(for example AUTOSAR, ISO 26262, ASIL-B, MISRA C, MATLAB/Simulink, CANoe, DOORS, "
    "Embedded Coder, XCP, Python, C/C++).\n"
    "4. Preserve ALL numbers, percentages, and dates exactly. Never convert, recompute, "
    "or re-order them. '8+ years' keeps the 8.\n"
    "5. Do NOT add, strengthen, or invent any claim, certification, qualification, or "
    "seniority. Translate hedges AS hedges — 'familiar with the objectives of X' must "
    "never become 'certified in X'.\n"
    "6. Write natural, idiomatic professional {target_language} as it appears on a real "
    "CV in that language — not literal word-for-word translation.\n"
    "7. Keep each value roughly its original length. These are CV bullets and headings.\n"
    "8. Output plain text values only. Never emit LaTeX commands or backslashes.\n"
    "9. This is an ENGINEERING CV. Read every ambiguous English term in its "
    "engineering sense, never its everyday sense. In control engineering a 'plant' "
    "or 'plant model' is the controlled system (German: Regelstrecke / "
    "Streckenmodell) — never a factory and never a botanical plant. A 'bus' is a "
    "data bus, a 'harness' is a wiring harness, 'commissioning' is Inbetriebnahme. "
    "When a term is standard jargon in the target language's engineering industry, "
    "use that jargon."
)


class TranslateCvRequest(BaseModel):
    language: str
    selected_bullet_ids: list[str] = []
    optimized_bullets: list[dict] = []
    job_ad_text: str = ""
    matched_phrases: list[str] = []
    provider: str | None = None
    model: str | None = None


def _parse_json_object(raw: str) -> dict:
    """Pull a JSON object out of a model response, fenced or bare."""
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fenced:
        text = fenced.group(1).strip()
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start:end + 1]
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("expected a JSON object")
    return parsed


@router.post("/translate-cv")
async def translate_cv(body: TranslateCvRequest):
    """Translate every editable CV string into the target language."""
    lang = get_language(body.language)
    if lang is None:
        codes = ", ".join(l.code for l in _LANGUAGES)
        raise HTTPException(400, f"Unsupported language '{body.language}'. Supported: {codes}")
    if body.language == "en":
        return {"translated": {}, "language": "en", "passed": True, "errors": [], "warnings": []}

    facts = load_facts()
    if not facts:
        raise HTTPException(400, "facts.yaml not found or empty")

    optimized_map = {
        o["id"]: o["text"] for o in body.optimized_bullets if "id" in o and "text" in o
    }
    cv_vars = _cv_vars(
        facts=facts, bullet_ids=body.selected_bullet_ids,
        optimized_map=optimized_map,
        job_ad_text=body.job_ad_text,
        matched_phrases=body.matched_phrases,
        language=body.language,
    )

    from app.cv_translate import collect_cv_strings
    source = collect_cv_strings(cv_vars)
    if not source:
        return {"translated": {}, "language": body.language, "passed": True,
                "errors": [], "warnings": []}

    factbank = load_factbank()

    # The fact bank already knows every proper noun that must survive. Handing
    # the model that exact list beats hoping rule 3's examples generalise.
    keep = sorted(
        {e for e in (factbank.all_entities | factbank.all_skills) if len(e) > 2},
        key=str.lower,
    )[:120]

    system = CV_TRANSLATE_SYSTEM_PROMPT.replace("{target_language}", lang.english_name)
    if keep:
        system += (
            "\n\nDO NOT TRANSLATE these exact terms — reproduce them character for "
            "character wherever they appear:\n" + ", ".join(keep)
        )

    llm = get_provider(body.provider, body.model)
    full = ""
    try:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(source, ensure_ascii=False, indent=2)},
        ]
        async for token in llm.chat(messages, stream=True):
            full += token
    except Exception as e:
        raise HTTPException(502, f"Translation provider error: {e}")
    finally:
        try:
            await llm.close()
        except Exception:
            pass

    try:
        parsed = _parse_json_object(full)
    except Exception as e:
        raise HTTPException(502, f"Translator returned unparseable JSON: {e}")

    # Keep only keys we asked for, as strings. A hallucinated key would address
    # nothing on substitution, but dropping it here keeps the response honest.
    translated = {
        k: v.strip() for k, v in parsed.items()
        if k in source and isinstance(v, str) and v.strip()
    }

    from app.translate import check_translation
    from app.guard.validator import validate_write_gate

    errors: list[dict] = []
    warnings: list[dict] = []

    missing = [k for k in source if k not in translated]
    if missing:
        warnings.append({
            "rule": "translate_coverage",
            "severity": "warning",
            "message": f"{len(missing)} of {len(source)} CV fields came back untranslated",
            "detail": "Those fields stay in English. Re-run translation to retry them.",
        })

    # Per-field number and entity preservation. Segment-wise, so an invented
    # figure is attributed to the bullet that grew it.
    #
    # The entity check only means something on prose fields. Job titles, degrees
    # and hobbies are *supposed* to change — the fact bank harvests "Test
    # Engineer" and "Embedded Software" as entities, so checking them there
    # reports every correct translation as a dropped proper noun.
    prose_keys = {"about"}
    for key, original in source.items():
        candidate = translated.get(key)
        if not candidate:
            continue
        is_prose = key in prose_keys or key.startswith("bullet.")
        check = check_translation(original, candidate, factbank)
        for e in check.get("errors", []):
            errors.append({**e, "message": f"[{key}] {e['message']}"})
        for w in check.get("warnings", []):
            if not is_prose and w.get("rule") == "translate_entities":
                continue
            warnings.append({**w, "message": f"[{key}] {w['message']}"})

    # Rules 5 and 9 on the whole translated CV — a hedge that collapsed into a
    # certification is a property of the text, not of any single field.
    gate = validate_write_gate("\n".join(translated.values()), factbank, body.language)
    errors.extend(
        {"rule": e.rule, "message": e.message, "detail": e.detail} for e in gate.errors
    )
    warnings.extend(
        {"rule": w.rule, "message": w.message, "detail": w.detail} for w in gate.warnings
    )

    return {
        "translated": translated,
        "language": body.language,
        "fields": len(source),
        "passed": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
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
    # Reject path-traversal and known shipped templates
    if "/" in template_name or "\\" in template_name or template_name.startswith("."):
        raise HTTPException(400, f"Invalid template name: '{template_name}'")
    shipped = {t["id"]: t for t in list_templates()}
    if template_name in shipped:
        raise HTTPException(
            400,
            f"'{template_name}' already exists. Choose a different name — "
            f"shipped templates cannot be overwritten.",
        )

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
            tpl_dir = PATHS_WORKSPACE / "templates" / template_name
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
