# ── Phase 5: Chat endpoints — SSE streaming + diff + accept ──

import difflib
import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.docs import write_file
from app.llm.provider import get_provider, list_available_models, list_providers

logger = logging.getLogger("latex_studio.chat")
router = APIRouter(prefix="/api/chat", tags=["chat"])

SYSTEM_PROMPT_PATH = Path(__file__).parent / "llm" / "prompts" / "latex_mode.md"
_system_prompt_cache: str | None = None


def _load_system_prompt() -> str:
    global _system_prompt_cache
    if _system_prompt_cache is None:
        if SYSTEM_PROMPT_PATH.exists():
            _system_prompt_cache = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        else:
            _system_prompt_cache = "You are a LaTeX code editor. Only edit formatting and structure."
    return _system_prompt_cache


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


# ── List providers ─────────────────────────────────────────────────────────────

@router.get("/providers")
async def get_providers():
    return {"providers": list_providers()}


# ── List models for a provider ─────────────────────────────────────────────────

@router.get("/models")
async def get_models(provider: str = ""):
    models = list_available_models(provider)
    return {"models": models}
