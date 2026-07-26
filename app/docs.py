"""Workspace file CRUD, template management, document creation, git auto-commit."""

import json
import shutil
from pathlib import Path

import jinja2
import yaml

WORKSPACE = Path(__file__).parent.parent / "workspace"
TEMPLATES = WORKSPACE / "templates"
FACTS_PATH = WORKSPACE / "facts.yaml"

# Per-document git storage — keep metadata outside workspace tree
# to avoid nested .git dirs being treated as submodules by the parent repo.
DOCGIT_DIR = WORKSPACE.parent / ".docgit"


def _git_dir(doc_path: str) -> Path:
    slug = doc_path.replace("/", "-").replace("\\", "-").strip("-")
    d = DOCGIT_DIR / slug
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Jinja2 environment for template rendering ──────────────────────────────────

_jinja_env = jinja2.Environment(
    block_start_string="\\BLOCK{",
    block_end_string="}",
    variable_start_string="\\VAR{",
    variable_end_string="}",
    comment_start_string="\\#{",
    comment_end_string="}",
    trim_blocks=True,
    autoescape=False,
    loader=jinja2.FileSystemLoader(str(TEMPLATES)),
)


def tex_escape(text: str) -> str:
    escapes = {
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
        "\\": r"\textbackslash{}",
    }
    return "".join(escapes.get(c, c) for c in str(text))


_jinja_env.filters["tex_escape"] = tex_escape


# ── Fact bank ─────────────────────────────────────────────────────────────────

def load_facts() -> dict:
    """Load and return the facts.yaml content. Returns {} if missing."""
    if not FACTS_PATH.exists():
        return {}
    return yaml.safe_load(FACTS_PATH.read_text(encoding="utf-8"))


def save_facts(data: dict) -> None:
    """Write facts back to facts.yaml."""
    FACTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    FACTS_PATH.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True), encoding="utf-8")


# ── Render ─────────────────────────────────────────────────────────────────────

def render_template(template_id: str, variables: dict) -> str:
    """
    Render a template's main.tex.j2 (or main.tex) against variables.
    For CV templates, facts are auto-loaded from facts.yaml if not provided.
    Returns the rendered text.
    """
    tpl_dir = TEMPLATES / template_id
    if not tpl_dir.exists():
        raise FileNotFoundError(f"Template '{template_id}' not found")

    # Auto-inject facts for CV templates
    tdata = _load_template_data(template_id)
    kind = tdata.get("kind", "")
    if kind == "cv" and "facts" not in variables and FACTS_PATH.exists():
        variables = {"facts": load_facts(), **variables}

    j2_file = template_id + "/main.tex.j2"
    j2_names = [n for n in _jinja_env.list_templates() if n == j2_file]
    if j2_names:
        tpl = _jinja_env.get_template(j2_file)
        return tpl.render(**variables)

    # Fallback: plain main.tex
    main_tex = tpl_dir / "main.tex"
    if main_tex.exists():
        return main_tex.read_text(encoding="utf-8")

    raise FileNotFoundError(f"Template '{template_id}' has no main.tex or main.tex.j2")


def _render_j2_folder(template_id: str, target_dir: Path, variables: dict) -> None:
    """Render all .j2 files from a template folder into target_dir."""
    tpl_dir = TEMPLATES / template_id
    for item in tpl_dir.iterdir():
        if item.name == "template.json":
            continue
        dest = target_dir / item.name
        if item.name.endswith(".j2"):
            out_name = item.name[:-3]
            tpl = _jinja_env.get_template(f"{template_id}/{item.name}")
            rendered = tpl.render(**variables)
            (target_dir / out_name).write_text(rendered, encoding="utf-8")
        elif item.is_dir():
            if not dest.exists():
                shutil.copytree(item, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dest)


def _load_template_data(template_id: str) -> dict:
    tjson = TEMPLATES / template_id / "template.json"
    if tjson.exists():
        return json.loads(tjson.read_text(encoding="utf-8"))
    return {}

# ── Low-level file ops ────────────────────────────────────────────────────────

def read_file(doc_path: str, filename: str = "main.tex") -> str:
    path = WORKSPACE / doc_path / filename
    if not path.exists():
        raise FileNotFoundError(f"{path} not found")
    return path.read_text(encoding="utf-8")


def write_file(doc_path: str, content: str, filename: str = "main.tex") -> None:
    path = WORKSPACE / doc_path / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def pdf_path(doc_path: str) -> Path:
    return WORKSPACE / doc_path / "out.pdf"


# ── Workspace init ────────────────────────────────────────────────────────────

def init_workspace() -> None:
    """Ensure workspace and required sub-directories exist."""
    WORKSPACE.mkdir(exist_ok=True)
    TEMPLATES.mkdir(exist_ok=True)
    (WORKSPACE / "letters").mkdir(exist_ok=True)


# ── Document listing ──────────────────────────────────────────────────────────

def list_documents() -> list[dict]:
    """
    Return all user-editable documents in the workspace (cv/, letters/<name>/ etc.).
    Excludes .build, templates, hidden folders, and the letters container itself.
    """
    if not WORKSPACE.exists():
        return []
    docs = []
    for entry in sorted(WORKSPACE.iterdir()):
        if not entry.is_dir():
            continue
        name = entry.name
        if name.startswith(".") or name == "templates":
            continue
        if name == "letters":
            if entry.is_dir():
                for sub in sorted(entry.iterdir()):
                    if sub.is_dir() and not sub.name.startswith("."):
                        sub_main = sub / "main.tex"
                        docs.append({
                            "path": f"letters/{sub.name}",
                            "name": sub.name.replace("_", " ").title(),
                            "kind": "letter",
                            "has_tex": sub_main.exists(),
                        })
            continue
        main_tex = entry / "main.tex"
        kind = "letter" if name.startswith("letter") else "cv"
        docs.append({
            "path": name,
            "name": name.replace("_", " ").title(),
            "kind": kind,
            "has_tex": main_tex.exists(),
        })
    return docs


# ── Template listing ──────────────────────────────────────────────────────────

def list_templates() -> list[dict]:
    """Return all available templates."""
    if not TEMPLATES.exists():
        return []
    templates = []
    for entry in sorted(TEMPLATES.iterdir()):
        if not entry.is_dir():
            continue
        tjson = entry / "template.json"
        has_j2 = any(f.suffix == ".j2" for f in entry.iterdir())
        has_tex = (entry / "main.tex").exists()
        if tjson.exists():
            data = json.loads(tjson.read_text(encoding="utf-8"))
            data["id"] = entry.name
            data["has_template"] = has_tex or has_j2 or (data.get("copy_from") is not None)
            templates.append(data)
    return templates


# ── Document creation from template ───────────────────────────────────────────

def create_document(name: str, template_id: str, variables: dict | None = None) -> dict:
    """
    Create a new document folder from a template.
    For CV templates, facts.yaml is auto-loaded as 'facts' if not provided.
    Returns the document info dict.
    """
    variables = variables or {}
    tpl_dir = TEMPLATES / template_id
    if not tpl_dir.exists():
        raise FileNotFoundError(f"Template '{template_id}' not found")

    tdata = _load_template_data(template_id)
    default_vars = tdata.get("variables", {})
    merged = {**default_vars, **variables}

    # Auto-inject facts for CV templates
    kind = tdata.get("kind", "cv")
    if kind == "cv" and "facts" not in merged and FACTS_PATH.exists():
        merged["facts"] = load_facts()

    # Determine target folder
    if kind == "letter":
        target_dir = WORKSPACE / "letters" / name
    else:
        target_dir = WORKSPACE / name

    if target_dir.exists():
        raise FileExistsError(f"Document '{name}' already exists")

    target_dir.mkdir(parents=True)

    has_copy_from = bool(tdata.get("copy_from"))
    has_j2 = any(f.suffix == ".j2" for f in tpl_dir.iterdir())

    # Step 1: copy static assets from source if copy_from is set
    if has_copy_from:
        src_dir = WORKSPACE / tdata["copy_from"]
        if src_dir.exists():
            for item in src_dir.iterdir():
                if item.name in (".build", "out.pdf", "__pycache__", ".gitignore"):
                    continue
                dest = target_dir / item.name
                if item.is_dir():
                    shutil.copytree(item, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, dest)
        else:
            # Fallback: copy class/pics bundled in the template directory
            for item in tpl_dir.iterdir():
                if item.name in ("template.json", "main.tex.j2"):
                    continue
                dest = target_dir / item.name
                if item.is_dir():
                    shutil.copytree(item, dest, dirs_exist_ok=True)
                elif item.name != "main.tex":
                    shutil.copy2(item, dest)

    # Step 2: render .j2 templates (overwrites main.tex if it was copied)
    if has_j2:
        _render_j2_folder(template_id, target_dir, merged)
    elif not has_copy_from:
        # Plain copy (no j2, no copy_from)
        for item in tpl_dir.iterdir():
            if item.name == "template.json":
                continue
            dest = target_dir / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)

    return {
        "path": str(target_dir.relative_to(WORKSPACE)).replace("\\", "/"),
        "name": name.replace("_", " ").title(),
        "kind": kind,
        "has_tex": (target_dir / "main.tex").exists(),
    }


# ── Document deletion ─────────────────────────────────────────────────────────

def delete_document(doc_path: str) -> None:
    target = WORKSPACE / doc_path
    if not target.exists():
        raise FileNotFoundError(f"Document '{doc_path}' not found")
    shutil.rmtree(target)


# ── Document file listing ─────────────────────────────────────────────────────

def list_doc_files(doc_path: str) -> list[str]:
    """List editable files in a document folder (tex, sty, cls, yaml, json)."""
    target = WORKSPACE / doc_path
    if not target.exists():
        return []
    editable_exts = {".tex", ".sty", ".cls", ".yaml", ".json"}
    files = []
    for item in sorted(target.iterdir()):
        if item.is_file() and item.suffix in editable_exts:
            files.append(item.name)
    return files


# ── Git auto-commit ──────────────────────────────────────────────────────────

def git_commit(doc_path: str, message: str = "Auto-commit after successful compile") -> None:
    import subprocess
    doc_dir = WORKSPACE / doc_path
    if not doc_dir.exists():
        return
    gd = _git_dir(doc_path)
    work_tree = str(doc_dir)
    git_dir_str = str(gd)
    try:
        subprocess.run(
            ["git", "--git-dir", git_dir_str, "--work-tree", work_tree, "add", "-A"],
            capture_output=True, timeout=10, check=False,
        )
        subprocess.run(
            ["git", "--git-dir", git_dir_str, "--work-tree", work_tree,
             "commit", "-m", message, "--allow-empty"],
            capture_output=True, timeout=10, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


def git_log(doc_path: str, max_count: int = 20) -> list[dict]:
    import subprocess
    doc_dir = WORKSPACE / doc_path
    if not doc_dir.exists():
        return []
    gd = _git_dir(doc_path)
    if not gd.exists():
        return []
    git_dir_str = str(gd)
    try:
        result = subprocess.run(
            ["git", "--git-dir", git_dir_str,
             "log", f"--max-count={max_count}", "--format=%H%n%ai%n%s"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        commits = []
        parts = result.stdout.strip().split("\n\n")
        for block in parts:
            if not block.strip():
                continue
            lines = block.strip().split("\n")
            if len(lines) >= 3:
                commits.append({"hash": lines[0][:7], "date": lines[1], "message": "\n".join(lines[2:])})
        return commits
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []


def git_init(doc_path: str) -> None:
    import subprocess
    doc_dir = WORKSPACE / doc_path
    if not doc_dir.exists():
        return
    gd = _git_dir(doc_path)
    work_tree = str(doc_dir)
    git_dir_str = str(gd)
    try:
        subprocess.run(
            ["git", "--git-dir", git_dir_str, "--work-tree", work_tree, "init"],
            capture_output=True, timeout=5, check=False,
        )
        (doc_dir / ".gitignore").write_text(
            ".build/\nout.pdf\n*.aux\n*.log\n*.out\n*.synctex*\n*.fdb_latexmk\n*.fls\n",
            encoding="utf-8",
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
