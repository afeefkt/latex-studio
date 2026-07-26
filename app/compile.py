"""LaTeX compilation + git auto-commit."""

import asyncio
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

BASE_WORKSPACE = Path(__file__).parent.parent / "workspace"


def _workspace() -> Path:
    """Resolve the active workspace root at call time.

    app.docs rebinds its module-level WORKSPACE to workspace/<profile>/ when a
    profile is active, so this must read the attribute rather than import the
    value — otherwise documents under a profile resolve to a path that doesn't
    exist and compile reports "main.tex not found".
    """
    try:
        import app.docs as _docs
        return _docs.WORKSPACE
    except Exception:
        return BASE_WORKSPACE

# MiKTeX installs to a user-local path that isn't always on PATH.
_MIKTEX_CANDIDATES = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "MiKTeX" / "miktex" / "bin" / "x64",
    Path(os.environ.get("LOCALAPPDATA", "")) / "MiKTeX" / "miktex" / "bin" / "x64",
    Path("C:/Program Files/MiKTeX/miktex/bin/x64"),
]
for _p in _MIKTEX_CANDIDATES:
    if _p.exists() and str(_p) not in os.environ.get("PATH", ""):
        os.environ["PATH"] = str(_p) + os.pathsep + os.environ.get("PATH", "")
        break


@dataclass
class CompileError:
    file: str
    line: int | None
    message: str
    kind: str = "error"
    translated: str = ""


@dataclass
class CompileResult:
    success: bool
    pdf_path: Path | None
    errors: list[CompileError] = field(default_factory=list)
    warnings: list[CompileError] = field(default_factory=list)
    log: str = ""
    git_committed: bool = False


# ── Plain-English error translations ───────────────────────────────────────────

ERROR_TRANSLATIONS: list[tuple[str, str]] = [
    (r"Undefined control sequence", "A command the template doesn't know"),
    (r"Misplaced alignment tab character &", "An unescaped & — use \\& instead"),
    (r"File .* not found", "A file or package the template needs is missing"),
    (r"Emergency stop", "A fatal error stopped compilation"),
    (r"Overfull \\\\hbox", "A line ran past the margin (cosmetic)"),
    (r"Underfull \\\\hbox", "Extra spacing warning (cosmetic)"),
    (r"LaTeX Error: Unknown option", "An option this class doesn't recognise"),
    (r"No pages of output", "The document produced no pages — check \\begin{document}"),
    (r"Missing \\\\begin", "A section or environment wasn't closed properly"),
    (r"There's no line here to end", "An extra \\\\ or \\newline without content"),
    (r"Too many \\}", "Extra closing brace somewhere"),
    (r"Paragraph ended before", "A command expected an argument but got a blank line"),
    (r"Missing number", "A command expected a number argument but got text"),
    (r"Display math should end", "Unclosed math mode — check for missing \\]"),
    (r"Runaway argument", "An unclosed brace in a command argument"),
    (r"Float\(s\) lost", "A figure or table couldn't be placed"),
    (r"I can't find file", "A file referenced in the document doesn't exist"),
    (r"Unknown option", "An option this document class or package doesn't recognise"),
]


def _translate_error(message: str) -> str:
    for pattern, translation in ERROR_TRANSLATIONS:
        if re.search(pattern, message, re.IGNORECASE):
            return translation
    return ""


def _parse_log(log_text: str) -> tuple[list[CompileError], list[CompileError]]:
    errors: list[CompileError] = []
    warnings: list[CompileError] = []

    error_re = re.compile(
        r"^(?P<file>[^\n:]+\.tex):(?P<line>\d+): (?P<msg>.+)$", re.MULTILINE
    )
    latex_error_re = re.compile(
        r"^! LaTeX Error: (?P<msg>.+?)(?:\.|$)", re.MULTILINE
    )
    bang_error_re = re.compile(
        r"^!(?: (?:Undefined control sequence|Emergency stop|I can't find file|Missing (?:\\begin|\\end|number|insert|\\right|\\left)|Extra|Paragraph ended|Display math|Infinite glue|Runaway|File not found|No pages|There's no line here|Illegal|Argument of|Too many|Capacity exceeded).*)$", re.MULTILINE
    )
    warn_re = re.compile(r"^LaTeX Warning: (?P<msg>.+)$", re.MULTILINE)
    box_re = re.compile(
        r"^(Overfull|Underfull) \\[hv]box.+at lines? (?P<line>\d+)", re.MULTILINE
    )
    pkg_re = re.compile(r"^Package \S+ Warning: (?P<msg>.+)$", re.MULTILINE)

    for m in error_re.finditer(log_text):
        errors.append(
            CompileError(
                file=m.group("file"),
                line=int(m.group("line")),
                message=m.group("msg").strip(),
            )
        )

    for m in latex_error_re.finditer(log_text):
        errors.append(
            CompileError(
                file="main.tex", line=None, message=f"LaTeX Error: {m.group('msg').strip()}"
            )
        )

    bang_lines = list(bang_error_re.finditer(log_text))
    for m in bang_lines:
        already_captured = any(m.group(0) in e.message for e in errors)
        if not already_captured:
            errors.append(
                CompileError(file="main.tex", line=None, message=m.group(0).strip())
            )

    for m in warn_re.finditer(log_text):
        warnings.append(
            CompileError(file="", line=None, message=m.group("msg").strip(), kind="warning")
        )

    for m in pkg_re.finditer(log_text):
        warnings.append(
            CompileError(file="", line=None, message=m.group("msg").strip(), kind="warning")
        )

    for m in box_re.finditer(log_text):
        warnings.append(
            CompileError(
                file="", line=int(m.group("line")), message=m.group(0).strip(), kind="warning"
            )
        )

    # Add plain-English translations to all errors and warnings
    for e in errors:
        e.translated = _translate_error(e.message)
    for w in warnings:
        w.translated = _translate_error(w.message)

    return errors, warnings


def _git_commit(src_dir: Path, doc_path: str = "") -> bool:
    """Auto-commit the document folder on successful compile. Returns True if committed."""
    try:
        import app.docs as _docs
        gd = _docs._git_dir(doc_path or src_dir.name)
        work_tree = str(src_dir)
        git_dir_str = str(gd)

        if not gd.exists():
            subprocess.run(
                ["git", "--git-dir", git_dir_str, "--work-tree", work_tree, "init"],
                capture_output=True, text=True, timeout=15,
            )
            (src_dir / ".gitignore").write_text(
                ".build/\nout.pdf\n*.aux\n*.log\n*.out\n*.synctex*\n*.fdb_latexmk\n*.fls\n",
                encoding="utf-8",
            )

        subprocess.run(
            ["git", "--git-dir", git_dir_str, "--work-tree", work_tree, "add", "-A"],
            capture_output=True, text=True, timeout=15,
        )

        status = subprocess.run(
            ["git", "--git-dir", git_dir_str, "diff", "--cached", "--quiet"],
            capture_output=True, timeout=15,
        )
        if status.returncode == 0:
            return False

        subprocess.run(
            ["git", "--git-dir", git_dir_str, "--work-tree", work_tree,
             "commit", "-m", "auto: successful compile"],
            capture_output=True, text=True, timeout=15,
        )
        return True
    except Exception:
        return False


async def compile_doc(doc_path: str) -> CompileResult:
    """Compile workspace/<doc_path>/main.tex with lualatex (two passes)."""

    src_dir = _workspace() / doc_path
    main_tex = src_dir / "main.tex"

    if not main_tex.exists():
        return CompileResult(
            success=False,
            pdf_path=None,
            errors=[CompileError(file="main.tex", line=None, message="main.tex not found")],
        )

    out_dir = src_dir / ".build"
    out_dir.mkdir(exist_ok=True)

    base_cmd = [
        "lualatex",
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-no-shell-escape",
        f"-output-directory={out_dir}",
        "main.tex",
    ]

    def _run_passes() -> tuple[int, str]:
        logs = []
        for _pass in range(2):
            r = subprocess.run(
                base_cmd,
                capture_output=True,
                text=True,
                cwd=str(src_dir),
                timeout=120,
            )
            logs.append(r.stdout or "")
            logs.append(r.stderr or "")
            # Only abort early on a real failure (no PDF produced).
            # MiKTeX emits a non-fatal "check for updates" warning that sets
            # returncode=1 even when compilation succeeded and a PDF exists.
            if r.returncode != 0 and not (out_dir / "main.pdf").exists():
                return r.returncode, "\n".join(logs)
        return r.returncode, "\n".join(logs)

    try:
        returncode, log_text = await asyncio.to_thread(_run_passes)
    except FileNotFoundError:
        return CompileResult(
            success=False,
            pdf_path=None,
            errors=[
                CompileError(
                    file="",
                    line=None,
                    message="lualatex not found. Ensure MiKTeX is installed and on PATH.",
                )
            ],
        )

    errors, warnings = _parse_log(log_text)
    pdf_candidate = out_dir / "main.pdf"

    if pdf_candidate.exists():
        stable_pdf = src_dir / "out.pdf"
        shutil.copy2(pdf_candidate, stable_pdf)
        committed = await asyncio.to_thread(_git_commit, src_dir, doc_path)
        return CompileResult(
            success=True, pdf_path=stable_pdf, errors=errors, warnings=warnings,
            log=log_text, git_committed=committed,
        )
    else:
        return CompileResult(
            success=False, pdf_path=None, errors=errors, warnings=warnings, log=log_text,
        )
