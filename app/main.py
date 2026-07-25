import subprocess
from pathlib import Path

import app.compile  # noqa: F401 -- triggers MiKTeX PATH patch on import
import app.docs as docs
from app.chat import router as chat_router
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.compile import compile_doc
from app.docs import (
    create_document,
    delete_document,
    init_workspace,
    list_doc_files,
    list_documents,
    list_templates,
    load_facts,
    pdf_path,
    read_file,
    render_template,
    save_facts,
    write_file,
)
from app.importer import import_to_facts

app = FastAPI(title="LaTeX Studio")

STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
app.include_router(chat_router)

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


# ── Document deletion ─────────────────────────────────────────────────────────

@app.delete("/api/docs/{doc_path:path}")
async def remove_doc(doc_path: str):
    try:
        delete_document(doc_path)
        return {"deleted": True}
    except FileNotFoundError:
        raise HTTPException(404, f"{doc_path} not found")


# ── Templates ─────────────────────────────────────────────────────────────────

@app.get("/api/templates")
async def get_templates():
    return {"templates": list_templates()}


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
            {"file": e.file, "line": e.line, "message": e.message, "kind": e.kind}
            for e in result.errors
        ],
        "warnings": [
            {"file": e.file, "line": e.line, "message": e.message, "kind": e.kind}
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


# ── SPA fallback ──────────────────────────────────────────────────────────────

@app.get("/{full_path:path}")
async def spa(full_path: str):
    return FileResponse(str(STATIC / "index.html"))
