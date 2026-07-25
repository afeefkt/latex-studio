import subprocess
from pathlib import Path

import app.compile  # noqa: F401 — triggers MiKTeX PATH patch on import

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.compile import compile_doc
from app.docs import pdf_path, read_file, write_file

app = FastAPI(title="LaTeX Studio")

STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


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
        version = "NOT INSTALLED — run: winget install MiKTeX.MiKTeX"
    return {"status": "ok", "lualatex": version}


# ── file CRUD ─────────────────────────────────────────────────────────────────

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


# ── compile ───────────────────────────────────────────────────────────────────

class CompileBody(BaseModel):
    path: str = "cv"


@app.post("/api/compile")
async def compile_endpoint(body: CompileBody):
    result = await compile_doc(body.path)
    return {
        "success": result.success,
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
        raise HTTPException(404, "PDF not found — compile first")
    return FileResponse(
        str(p),
        media_type="application/pdf",
        headers={"Cache-Control": "no-store"},
    )


# ── SPA fallback ──────────────────────────────────────────────────────────────

@app.get("/{full_path:path}")
async def spa(full_path: str):
    return FileResponse(str(STATIC / "index.html"))
