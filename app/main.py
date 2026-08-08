import json
import os
import subprocess
from pathlib import Path

import app.compile  # noqa: F401 -- triggers MiKTeX PATH patch on import
import app.docs as docs
from app.chat import router as chat_router
from app.content import router as content_router
from app.paths import DATA_ROOT, STATIC_DIR
from app.tracker import list_applications as tracker_list, update_application as tracker_update
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.compile import compile_doc
from app.docs import (
    _safe_target,
    create_document,
    create_profile,
    delete_document,
    get_active_profile,
    init_workspace,
    list_doc_files,
    list_documents,
    list_templates,
    load_facts,
    load_profiles,
    pdf_path,
    read_file,
    render_template,
    save_facts,
    save_profiles,
    set_active_profile,
    write_file,
)
from app.importer import import_to_facts

app = FastAPI(title="LaTeX Studio")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(chat_router)
app.include_router(content_router)

# ── Startup ───────────────────────────────────────────────────────────────────

init_workspace()


# ── health ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    try:
        result = subprocess.run(
            ["lualatex", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        version = result.stdout.splitlines()[0] if result.stdout else "unknown"
    except FileNotFoundError:
        version = "NOT INSTALLED -- run: winget install MiKTeX.MiKTeX"
    return {"status": "ok", "lualatex": version}


# ── API key management ────────────────────────────────────────────────────────

_ENV_KEY_MAP = {
    "deepseek":     "DEEPSEEK_API_KEY",
    "nvidia":       "NVIDIA_API_KEY",
    "openrouter":   "OPENROUTER_API_KEY",
    "ollama_url":   "OLLAMA_BASE_URL",
    "ollama_model": "OLLAMA_MODEL",
}


def _update_env_file(path: Path, key: str, value: str) -> None:
    """Set or replace a KEY=VALUE line in an .env file."""
    if not path.exists():
        path.write_text(f"{key}={value}\n", encoding="utf-8")
        return
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    found = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(f"{key}=") or stripped.startswith(f"# {key}="):
            if value:
                lines[i] = f"{key}={value}\n"
            else:
                lines[i] = f"# {key}=\n"
            found = True
            break
    if not found and value:
        lines.append(f"{key}={value}\n")
    path.write_text("".join(lines), encoding="utf-8")


class ApiKeyBody(BaseModel):
    provider: str
    value: str = ""


@app.post("/api/settings/apikey")
async def save_apikey(body: ApiKeyBody):
    if body.provider not in _ENV_KEY_MAP:
        raise HTTPException(400, f"Unknown provider: {body.provider}")
    env_key = _ENV_KEY_MAP[body.provider]
    env_path = DATA_ROOT / ".env"
    _update_env_file(env_path, env_key, body.value.strip())
    if body.value.strip():
        os.environ[env_key] = body.value.strip()
    else:
        os.environ.pop(env_key, None)
    load_dotenv(env_path, override=True)
    return {"ok": True}


# ── Document list ─────────────────────────────────────────────────────────────

@app.get("/api/docs")
async def get_documents():
    return {"documents": list_documents()}


# ── Document files ────────────────────────────────────────────────────────────

@app.get("/api/docs/{doc_path:path}/files")
async def get_doc_files(doc_path: str):
    try:
        files = list_doc_files(doc_path)
        return {"files": files}
    except FileNotFoundError:
        raise HTTPException(404, f"{doc_path} not found")


# ── File CRUD ─────────────────────────────────────────────────────────────────

@app.get("/api/docs/{doc_path:path}")
async def get_doc(doc_path: str, file: str = "main.tex"):
    try:
        content = read_file(doc_path, file)
        return PlainTextResponse(content)
    except FileNotFoundError:
        raise HTTPException(404, f"{doc_path}/{file} not found")


class SaveBody(BaseModel):
    content: str
    file: str = "main.tex"


@app.post("/api/docs/{doc_path:path}")
async def save_doc(doc_path: str, body: SaveBody):
    write_file(doc_path, body.content, body.file)
    return {"saved": True}


# ── Workspace file upload / delete ────────────────────────────────────────────

from fastapi import UploadFile, File as FastFile


@app.post("/api/docs/{doc_path:path}/upload")
async def upload_workspace_file(doc_path: str, file: UploadFile = FastFile(...)):
    if not file.filename:
        raise HTTPException(400, "No file selected")
    if "/" in file.filename or "\\" in file.filename or file.filename.startswith("."):
        raise HTTPException(400, "Invalid filename")
    allowed = {".jpg", ".jpeg", ".png", ".gif", ".pdf", ".eps", ".svg",
                ".cls", ".sty", ".bst", ".bib", ".lua", ".fd", ".def", ".lco"}
    suffix = Path(file.filename).suffix.lower()
    if suffix not in allowed:
        raise HTTPException(400, f"Unsupported file type: {suffix}")
    target = _safe_target(doc_path) / file.filename
    content = await file.read()
    target.write_bytes(content)
    return {"ok": True, "filename": file.filename, "bytes": len(content)}


@app.delete("/api/docs/{doc_path:path}/file/{filename:path}")
async def delete_workspace_file(doc_path: str, filename: str):
    # Allow forward slashes for subdir files (e.g. pics/photo.jpg) but block traversal
    if "\\" in filename or filename.startswith(".") or ".." in filename.split("/"):
        raise HTTPException(400, "Invalid filename")
    if filename in ("main.tex", "main.tex.j2"):
        raise HTTPException(400, "Cannot delete main.tex — the document would become uncompileable")
    base = _safe_target(doc_path)
    target = (base / filename).resolve()
    if not str(target).startswith(str(base.resolve())):
        raise HTTPException(400, "Invalid filename")
    if not target.exists():
        raise HTTPException(404, f"File '{filename}' not found")
    target.unlink()
    return {"ok": True}


# ── Import custom CV (paste .tex + .cls + extra files) ────────────────────────

from datetime import datetime, timezone as dt_timezone


class ImportCustomBody(BaseModel):
    name: str
    tex_content: str
    cls_content: str = ""
    cls_filename: str = "custom.cls"
    extra_files: list[dict] = []


_ALLOWED_IMPORT_EXTS = {".tex", ".cls", ".sty", ".bst", ".bib", ".lua", ".cfg", ".def", ".fd", ".clo"}


@app.post("/api/docs/import-custom")
async def import_custom_cv(body: ImportCustomBody):
    name = body.name.strip().replace(" ", "_").lower()[:80]
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(400, f"Invalid document name: '{body.name}'")
    tex_content = body.tex_content.strip()
    if not tex_content:
        raise HTTPException(400, "tex_content is required")

    target_dir = docs.WORKSPACE / name
    if target_dir.exists():
        raise HTTPException(409, f"Document '{name}' already exists")
    target_dir.mkdir(parents=True)

    (target_dir / "main.tex").write_text(tex_content, encoding="utf-8")

    if body.cls_content.strip():
        cls_fn = (body.cls_filename or "custom.cls").strip().replace("\\", "/").split("/")[-1]
        if not cls_fn.startswith(".") and not ".." in cls_fn and Path(cls_fn).suffix.lower() in _ALLOWED_IMPORT_EXTS:
            (target_dir / cls_fn).write_text(body.cls_content.strip(), encoding="utf-8")

    for ef in body.extra_files:
        fn = (ef.get("name") or "").strip().replace("\\", "/").split("/")[-1]
        fc = (ef.get("content") or "").strip()
        if not fn or fn.startswith(".") or ".." in fn:
            continue
        if Path(fn).suffix.lower() not in _ALLOWED_IMPORT_EXTS:
            continue
        (target_dir / fn).write_text(fc, encoding="utf-8")

    manifest = {
        "schema": 1,
        "created_utc": datetime.now(dt_timezone.utc).isoformat().replace("+00:00", "Z"),
        "origin": "import",
        "kind": "cv",
        "template_id": "import-custom",
        "language": "en",
        "translated": False,
        "company": "",
        "role": "",
        "channel": "",
    }
    (target_dir / "document.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return {
        "created": True,
        "document": {
            "path": str(target_dir.relative_to(docs.WORKSPACE)).replace("\\", "/"),
            "name": name.replace("_", " ").title(),
            "kind": "cv",
            "has_tex": True,
        },
    }


# ── Document deletion ─────────────────────────────────────────────────────────

@app.delete("/api/docs/{doc_path:path}")
async def remove_doc(doc_path: str):
    try:
        delete_document(doc_path)
        return {"deleted": True}
    except FileNotFoundError:
        raise HTTPException(404, f"{doc_path} not found")
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))


# ── Templates ─────────────────────────────────────────────────────────────────

@app.get("/api/templates")
async def get_templates():
    return {"templates": list_templates()}


# ── i18n ──────────────────────────────────────────────────────────────────────

from app.i18n import SUPPORTED as _LANGUAGES, to_dict as _lang_to_dict


@app.get("/api/i18n/languages")
async def get_languages():
    return {"languages": [_lang_to_dict(l) for l in _LANGUAGES]}


class CreateBody(BaseModel):
    name: str
    template_id: str
    variables: dict = {}


@app.post("/api/templates/{template_id}/create")
async def create_from_template(template_id: str, body: CreateBody):
    try:
        doc_info = create_document(body.name, template_id, body.variables)
        return {"created": True, "document": doc_info}
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except FileExistsError as e:
        raise HTTPException(409, str(e))


# ── Render (preview template without creating a document) ─────────────────────

class RenderBody(BaseModel):
    template_id: str
    variables: dict = {}


@app.post("/api/render")
async def render_doc(body: RenderBody):
    try:
        rendered = render_template(body.template_id, body.variables)
        return PlainTextResponse(rendered)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


# ── Fact bank ─────────────────────────────────────────────────────────────────

@app.get("/api/facts")
async def get_facts():
    facts = load_facts()
    return facts


class FactsBody(BaseModel):
    facts: dict


@app.post("/api/facts")
async def update_facts(body: FactsBody):
    try:
        save_facts(body.facts)
        return {"saved": True}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/facts/raw")
async def get_facts_raw():
    """Return raw YAML text of facts.yaml for editor display."""
    try:
        content = read_file("", "facts.yaml")
        return PlainTextResponse(content)
    except FileNotFoundError:
        raise HTTPException(404, "facts.yaml not found")


class RawFactsBody(BaseModel):
    yaml_text: str


# Any real facts.yaml has at least one of these. A payload with none of them is
# not facts — most likely an API error body echoed back by a client that didn't
# check response.ok. Writing it would destroy the fact bank.
_FACTS_KEYS = {
    "identity", "roles", "skills", "education", "languages", "awards",
    "hobbies", "banned_claims", "certifications_held", "certifications_in_progress",
}


@app.post("/api/facts/raw")
async def update_facts_raw(body: RawFactsBody):
    """Accept raw YAML, validate, and save facts.yaml."""
    import yaml as _yaml
    try:
        data = _yaml.safe_load(body.yaml_text)
        if not isinstance(data, dict):
            raise ValueError("facts.yaml must be a YAML dictionary")
    except Exception as e:
        raise HTTPException(400, f"Invalid YAML: {e}")
    if not _FACTS_KEYS & data.keys():
        raise HTTPException(
            400,
            "Refusing to save: no recognised facts.yaml sections found "
            f"(expected at least one of {', '.join(sorted(_FACTS_KEYS))}). "
            "This usually means an error response was pasted into the editor.",
        )
    save_facts(data)
    return {"saved": True}


# ── Import ─────────────────────────────────────────────────────────────────────

class ImportBody(BaseModel):
    text: str


@app.post("/api/import")
async def import_work_history(body: ImportBody):
    """Parse work history text and return structured facts. Does NOT save."""
    try:
        existing = load_facts()
        merged = import_to_facts(body.text, existing)
        return {"facts": merged, "roles_found": len(merged.get("roles", []))}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Compile ───────────────────────────────────────────────────────────────────

class CompileBody(BaseModel):
    path: str = "cv"


@app.post("/api/compile")
async def compile_endpoint(body: CompileBody):
    result = await compile_doc(body.path)
    return {
        "success": result.success,
        "git_committed": result.git_committed,
        "pdf_url": f"/api/pdf/{body.path}" if result.success else None,
        "errors": [
            {"file": e.file, "line": e.line, "message": e.message, "kind": e.kind,
             "translated": e.translated}
            for e in result.errors
        ],
        "warnings": [
            {"file": e.file, "line": e.line, "message": e.message, "kind": e.kind,
             "translated": e.translated}
            for e in result.warnings
        ],
        "log": result.log,
    }


# ── PDF serving ───────────────────────────────────────────────────────────────

@app.api_route("/api/pdf/{doc_path:path}", methods=["GET", "HEAD"])
async def get_pdf(doc_path: str):
    p = pdf_path(doc_path)
    if not p.exists():
        raise HTTPException(404, "PDF not found -- compile first")
    return FileResponse(
        str(p),
        media_type="application/pdf",
        headers={"Cache-Control": "no-store"},
    )


# ── Git history ───────────────────────────────────────────────────────────────

@app.get("/api/git/{doc_path:path}")
async def git_log(doc_path: str):
    return {"commits": docs.git_log(doc_path)}


# ── Profiles ──────────────────────────────────────────────────────────────────

@app.get("/api/profiles")
async def list_profiles_endpoint():
    """List all profiles and the currently active one."""
    return {
        "profiles": load_profiles(),
        "active": get_active_profile(),
    }


class ProfileBody(BaseModel):
    name: str


@app.post("/api/profiles")
async def create_profile_endpoint(body: ProfileBody):
    """Create a new profile."""
    try:
        profile = create_profile(body.name)
        return {"created": True, "profile": profile}
    except ValueError as e:
        raise HTTPException(400, str(e))


class SwitchProfileBody(BaseModel):
    id: str


@app.post("/api/profiles/switch")
async def switch_profile_endpoint(body: SwitchProfileBody):
    """Switch to a different profile."""
    profiles = load_profiles()
    if not any(p["id"] == body.id for p in profiles):
        raise HTTPException(404, f"Profile '{body.id}' not found")
    set_active_profile(body.id)
    return {"active": body.id, "message": f"Switched to profile '{body.id}'"}


# ── Applications tracker ───────────────────────────────────────────────────────

@app.get("/api/applications")
async def list_applications():
    return {"applications": tracker_list()}


class UpdateAppBody(BaseModel):
    field: str
    value: str


@app.post("/api/applications/{index}")
async def update_application(index: int, body: UpdateAppBody):
    ok = tracker_update(index, body.field, body.value)
    if not ok:
        raise HTTPException(400, f"Could not update application {index}")
    return {"updated": True}


# ── SPA fallback ──────────────────────────────────────────────────────────────

@app.get("/{full_path:path}")
async def spa(full_path: str):
    return FileResponse(str(STATIC_DIR / "index.html"))
