# ── Phase 5: Chat endpoints — SSE streaming + diff + accept ──

import difflib
import json
import logging
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.compile import compile_doc
from app.content import yaml_dump_facts
from app.docs import list_doc_files, load_facts, read_file, write_file
from app.llm.provider import get_provider, list_available_models, list_providers
from app.paths import PROMPTS_DIR

logger = logging.getLogger("latex_studio.chat")
router = APIRouter(prefix="/api/chat", tags=["chat"])

SYSTEM_PROMPT_PATH = PROMPTS_DIR / "latex_mode.md"
_system_prompt_cache: str | None = None


def _load_system_prompt() -> str:
    global _system_prompt_cache
    if _system_prompt_cache is None:
        if SYSTEM_PROMPT_PATH.exists():
            _system_prompt_cache = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        else:
            _system_prompt_cache = "You are a LaTeX code editor. Only edit formatting and structure."
    return _system_prompt_cache


TEXT_CONTEXT_SUFFIXES = {
    ".tex", ".cls", ".sty", ".bib", ".bst", ".lco", ".def", ".fd", ".lua", ".txt",
}
MAX_CONTEXT_FILE_CHARS = 12000
MAX_CONTEXT_TOTAL_CHARS = 50000


def _extract_fenced(text: str, lang: str) -> str | None:
    match = re.search(rf"```{re.escape(lang)}\s*([\s\S]*?)```", text, re.IGNORECASE)
    return match.group(1).strip() if match else None


def _patch_snippet(original: str, snippet: str) -> str | None:
    """
    Find where a proposed snippet fits into the original document and
    return the full patched document. Returns None if no match found.

    Uses a sliding window to find the best position where the snippet lines
    most closely match the original, then replaces that region.
    """
    snippet_lines = snippet.strip().splitlines()
    orig_lines = original.splitlines()

    if not snippet_lines or len(snippet_lines) > len(orig_lines):
        return None

    # Sliding window: find position in original where snippet best matches
    best_pos = 0
    best_score = 0

    for i in range(len(orig_lines) - len(snippet_lines) + 1):
        score = 0
        for j, sl in enumerate(snippet_lines):
            sl_stripped = sl.strip()
            ol_stripped = orig_lines[i + j].strip() if i + j < len(orig_lines) else ""
            if sl_stripped == ol_stripped:
                score += 1
            elif sl_stripped and ol_stripped:
                # Partial credit for similar lines (whitespace/comment diffs)
                ratio = difflib.SequenceMatcher(None, sl_stripped, ol_stripped).ratio()
                if ratio > 0.7:
                    score += ratio * 0.5
        if score > best_score:
            best_score = score
            best_pos = i

    # Require at least one exact match or very high similarity
    if best_score < 0.5:
        return None

    # Replace the matching region
    result = orig_lines[:best_pos] + snippet_lines + orig_lines[best_pos + len(snippet_lines):]
    return "\n".join(result)


def _workspace_context(doc_path: str, active_file: str) -> str:
    """Build bounded context from files inside the selected document folder."""
    try:
        files = list_doc_files(doc_path)
    except Exception as e:
        return f"Could not list document files: {e}"

    names = [f["name"] if isinstance(f, dict) else str(f) for f in files]
    lines = [
        f"Selected document folder: {doc_path}",
        f"Active file: {active_file}",
        "Files in this document folder:",
        *[f"- {name}" for name in names],
    ]

    total = 0
    for name in names:
        suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if name == active_file or suffix not in TEXT_CONTEXT_SUFFIXES:
            continue
        if total >= MAX_CONTEXT_TOTAL_CHARS:
            break
        try:
            content = read_file(doc_path, name)
        except Exception:
            continue
        if not content.strip():
            continue
        budget = min(MAX_CONTEXT_FILE_CHARS, MAX_CONTEXT_TOTAL_CHARS - total)
        excerpt = content[:budget]
        total += len(excerpt)
        truncated = "\n... [truncated]" if len(content) > len(excerpt) else ""
        lines.append(f"\n--- {name} ---\n{excerpt}{truncated}")

    return "\n".join(lines)


EDIT_RESPONSE_INSTRUCTIONS = """
When changing the document, return exactly one fenced JSON block. Do not return prose.

Preferred formats:
```json
{"mode":"search_replace","search":"exact existing text","replace":"new text"}
```

or, when the edit is broad or context matching may be fragile:
```json
{"mode":"replace_file","content":"the complete new content of the active file"}
```

Rules:
- `search` must be copied byte-for-byte from the active file.
- `replace_file` must contain the complete active file, not only a snippet.
- Only edit the active file unless the user explicitly names another file.
""".strip()


def _apply_structured_edit(original: str, raw_response: str) -> tuple[str | None, str]:
    """Apply JSON/search-replace/full-file edits, falling back to legacy tex snippets."""
    json_block = _extract_fenced(raw_response, "json")
    if json_block:
        try:
            payload = json.loads(json_block)
        except json.JSONDecodeError as e:
            return None, f"LLM returned invalid edit JSON: {e}"
        mode = str(payload.get("mode", "")).strip()
        if mode == "replace_file":
            content = payload.get("content")
            if isinstance(content, str) and content.strip():
                return content, "replace_file"
            return None, "replace_file edit did not include content"
        if mode == "search_replace":
            search = payload.get("search")
            replace = payload.get("replace")
            if not isinstance(search, str) or not search:
                return None, "search_replace edit did not include search text"
            if not isinstance(replace, str):
                return None, "search_replace edit did not include replacement text"
            count = original.count(search)
            if count == 1:
                return original.replace(search, replace, 1), "search_replace"
            if count == 0:
                return None, "Search text was not found in the active file"
            return None, "Search text matched more than once; edit would be ambiguous"
        return None, f"Unknown edit mode: {mode or '(missing)'}"

    search_block = _extract_fenced(raw_response, "search")
    replace_block = _extract_fenced(raw_response, "replace")
    if search_block is not None and replace_block is not None:
        count = original.count(search_block)
        if count == 1:
            return original.replace(search_block, replace_block, 1), "search_replace"
        return None, "Search block was not found uniquely in the active file"

    tex_block = _extract_fenced(raw_response, "tex")
    if tex_block:
        if "\\documentclass" in tex_block or "\\begin{document}" in tex_block:
            return tex_block, "replace_file"
        patched = _patch_snippet(original, tex_block)
        if patched is not None:
            return patched, "legacy_snippet"
        return None, "Could not locate snippet in document. The context lines may not match."

    return None, "No machine-applicable edit block found"


# ── Request models ─────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    messages: list[dict]
    provider: str | None = None
    model: str | None = None
    doc_content: str | None = None


class DiffRequest(BaseModel):
    original: str
    proposed: str


class AcceptRequest(BaseModel):
    text: str
    doc_path: str = "cv"
    file: str = "main.tex"


class ApplyFixRequest(BaseModel):
    doc_path: str = "cv"
    file: str = "main.tex"
    prompt: str  # The user's editing request
    provider: str | None = None
    model: str | None = None

MAX_FIX_ITERATIONS = 3


def _inject_facts(messages: list[dict]) -> list[dict]:
    """Insert facts.yaml context into the message list so the LLM knows what's real."""
    try:
        facts = load_facts()
    except Exception:
        return messages
    if not facts:
        return messages
    facts_block = yaml_dump_facts(facts)
    messages.insert(2, {
        "role": "user",
        "content": f"Here is the candidate's facts.yaml (the ONLY source of truth for factual claims):\n\n```yaml\n{facts_block}\n```",
    })
    messages.insert(3, {
        "role": "assistant",
        "content": "I see the document and the fact bank. I will only use facts from facts.yaml for any content changes.",
    })
    return messages


# ── SSE streaming endpoint ─────────────────────────────────────────────────────

@router.post("/stream")
async def chat_stream(body: ChatRequest):
    provider_name = body.provider
    model_name = body.model
    messages = body.messages

    system_prompt = _load_system_prompt()
    full_messages = [{"role": "system", "content": system_prompt}]

    # Inject current document content as context
    if body.doc_content:
        full_messages.append({
            "role": "user",
            "content": f"Here is the current LaTeX document:\n\n```tex\n{body.doc_content}\n```",
        })
        full_messages.append({
            "role": "assistant",
            "content": "I see the document. I'll help you edit it. What changes would you like?",
        })

    full_messages += messages
    _inject_facts(full_messages)

    async def event_generator():
        llm = None
        try:
            llm = get_provider(provider_name, model_name)
            logger.info(f"Chat stream started: provider={llm.provider_name}, model={llm.model_name}")

            full = ""
            async for token in llm.chat(full_messages, stream=True):
                full += token
                yield f"data: {json.dumps({'token': token})}\n\n"

            yield f"event: done\ndata: {json.dumps({'status': 'complete', 'full_text': full})}\n\n"
            logger.info(f"Chat stream complete: {len(full)} chars")

        except ValueError as e:
            logger.error(f"Provider error: {e}")
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
        except Exception as e:
            logger.error(f"LLM request failed: {e}")
            yield f"event: error\ndata: {json.dumps({'error': f'LLM request failed: {e}'})}\n\n"
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


# ── Diff generation ────────────────────────────────────────────────────────────

@router.post("/diff")
async def generate_diff(body: DiffRequest):
    original = body.original
    proposed = body.proposed

    # Try to patch the snippet into the original to get the full document
    patched = _patch_snippet(original, proposed)
    if patched is None:
        # Fallback: snippet doesn't match — show raw diff against full doc
        patched = proposed

    original_lines = original.splitlines(keepends=True)
    patched_lines = patched.splitlines(keepends=True)

    diff_lines = list(difflib.unified_diff(
        original_lines,
        patched_lines,
        fromfile="current",
        tofile="patched",
        n=3,
    ))

    return {
        "diff": "".join(diff_lines) if diff_lines else "",
        "has_changes": len(diff_lines) > 0,
        "patched": patched,
        "proposed": proposed,
    }


# ── Accept patch ───────────────────────────────────────────────────────────────

@router.post("/accept")
async def accept_patch(body: AcceptRequest):
    try:
        write_file(body.doc_path, body.text, body.file)
        return {"accepted": True}
    except Exception as e:
        raise HTTPException(500, f"Failed to save: {e}")


# ── Apply & Fix (auto-apply + compile-fix loop) ─────────────────────────────────

FIX_SYSTEM_PROMPT = """
You are a LaTeX debugger. The user asked for a change. You made it. Now the compilation failed.

Your job: fix ONLY the errors listed below. Return the corrected snippet.

RULES:
- Return only the corrected lines with 3-5 unchanged context lines above/below.
- Do NOT undo the original user change — fix around it.
- Return only a ```tex code block with the corrected snippet.
- If you cannot fix it, return: UNABLE_TO_FIX
""".strip()


async def _ask_llm(messages: list[dict], provider: str | None, model: str | None) -> str:
    """Call LLM with streaming, collect full response."""
    llm = None
    try:
        llm = get_provider(provider, model)
        full = ""
        async for token in llm.chat(messages, stream=True):
            full += token
        return full
    finally:
        if llm:
            try:
                await llm.close()
            except Exception:
                pass


@router.post("/apply-and-fix")
async def apply_and_fix(body: ApplyFixRequest):
    prompt = body.prompt
    doc_path = body.doc_path
    filename = body.file
    provider = body.provider
    model = body.model

    # Read current document
    try:
        current_content = read_file(doc_path, filename)
    except FileNotFoundError:
        raise HTTPException(404, "Document not found")
    except PermissionError as e:
        raise HTTPException(403, str(e))

    system_prompt = _load_system_prompt()
    document_context = _workspace_context(doc_path, filename)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": (
            f"{document_context}\n\n"
            f"Active file content ({filename}):\n\n```tex\n{current_content}\n```\n\n"
            f"{EDIT_RESPONSE_INSTRUCTIONS}"
        )},
        {"role": "assistant", "content": "I see the active file, its sibling files, and the edit contract. I will return a machine-applicable edit."},
        {"role": "user", "content": prompt},
    ]
    _inject_facts(messages)

    original_content = current_content

    async def event_generator():
        nonlocal current_content
        llm = None

        for iteration in range(1, MAX_FIX_ITERATIONS + 1):
            is_first = (iteration == 1)
            is_fix = not is_first

            if is_first:
                yield f"event: status\ndata: {json.dumps({'step': 'asking', 'message': 'Asking LLM for edit...'})}\n\n"
            else:
                yield f"event: status\ndata: {json.dumps({'step': 'fixing', 'message': f'Asking LLM to fix errors (attempt {iteration-1}/{MAX_FIX_ITERATIONS})...'})}\n\n"

            # Call LLM
            llm_response = ""
            try:
                llm = get_provider(provider, model)
                async for token in llm.chat(messages, stream=True):
                    llm_response += token
                    yield f"data: {json.dumps({'token': token})}\n\n"
            except Exception as e:
                yield f"event: error\ndata: {json.dumps({'error': f'LLM request failed: {e}'})}\n\n"
                return
            finally:
                if llm:
                    try:
                        await llm.close()
                    except Exception:
                        pass
                llm = None

            if not llm_response.strip():
                yield f"event: error\ndata: {json.dumps({'error': 'LLM returned empty response'})}\n\n"
                return

            logger.info(f"Iteration {iteration}: LLM returned {len(llm_response)} chars")

            # Extract tex code block — if absent, treat as conversational reply
            has_edit_block = any(
                re.search(rf"```{lang}\s*[\s\S]*?```", llm_response, re.IGNORECASE)
                for lang in ("json", "search", "replace", "tex")
            )
            if not has_edit_block:
                yield f"event: done\ndata: {json.dumps({'success': False, 'reply': llm_response, 'iterations': iteration})}\n\n"
                return

            if "UNABLE_TO_FIX" in llm_response:
                yield f"event: error\ndata: {json.dumps({'error': 'LLM was unable to fix the errors'})}\n\n"
                return

            patched, apply_mode = _apply_structured_edit(current_content, llm_response)
            if patched is None:
                yield f"event: error\ndata: {json.dumps({'error': apply_mode})}\n\n"
                return
            logger.info(f"Iteration {iteration}: applied edit mode={apply_mode}, chars={len(patched)}")

            current_content = patched

            # Write patched file
            write_file(doc_path, patched, filename)
            yield f"event: status\ndata: {json.dumps({'step': 'applied', 'message': 'Edit applied'})}\n\n"

            # Compile
            yield f"event: status\ndata: {json.dumps({'step': 'compiling', 'message': 'Compiling...'})}\n\n"
            logger.info(f"Iteration {iteration}: compiling...")

            compile_result = await compile_doc(doc_path)

            compile_errors = [
                {"file": e.file, "line": e.line, "message": e.message, "kind": e.kind, "translated": e.translated}
                for e in compile_result.errors
            ]
            compile_warnings = [
                {"file": e.file, "line": e.line, "message": e.message, "kind": e.kind, "translated": e.translated}
                for e in compile_result.warnings
            ]

            yield f"event: compile\ndata: {json.dumps({'success': compile_result.success, 'errors': compile_errors, 'warnings': compile_warnings, 'iteration': iteration})}\n\n"

            if compile_result.success:
                # Generate final diff
                diff_lines = list(difflib.unified_diff(
                    original_content.splitlines(keepends=True),
                    current_content.splitlines(keepends=True),
                    fromfile="current", tofile="patched", n=3,
                ))
                diff_text = "".join(diff_lines) if diff_lines else ""

                yield f"event: done\ndata: {json.dumps({'success': True, 'iterations': iteration, 'patched': current_content, 'diff': diff_text, 'warnings': compile_warnings})}\n\n"
                return

            # Compilation failed — prepare fix message for next iteration
            error_text = "\n".join(
                f"  L{e.get('line', '?')}: {e.get('message', '')}"
                for e in compile_errors[:10]
            )
            if not error_text:
                error_text = compile_result.log[-500:] if compile_result.log else "Unknown compilation error"

            logger.info(f"Iteration {iteration}: compilation failed — {len(compile_errors)} errors")

            messages.append({"role": "assistant", "content": llm_response})
            messages.append({"role": "user", "content": (
                f"Compilation failed with errors:\n\n{error_text}\n\n"
                f"Current active file content ({filename}):\n\n```tex\n{current_content}\n```\n\n"
                f"{EDIT_RESPONSE_INSTRUCTIONS}\n\n{FIX_SYSTEM_PROMPT}"
            )})

        # Max iterations reached
        yield f"event: done\ndata: {json.dumps({'success': False, 'iterations': MAX_FIX_ITERATIONS, 'message': f'Could not fix after {MAX_FIX_ITERATIONS} iterations', 'patched': current_content})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── List providers ─────────────────────────────────────────────────────────────

@router.get("/providers")
async def get_providers():
    return {"providers": list_providers()}


# ── List models for a provider ─────────────────────────────────────────────────

@router.get("/models")
async def get_models(provider: str = ""):
    models = list_available_models(provider)
    return {"models": models}
