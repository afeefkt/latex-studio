import asyncio
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

WORKSPACE = Path(__file__).parent.parent / "workspace"

# MiKTeX installs to a user-local path that isn't always on PATH.
# Add it so latexmk is findable even when the server started before PATH was set.
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
    kind: str = "error"  # "error" | "warning"


@dataclass
class CompileResult:
    success: bool
    pdf_path: Path | None
    errors: list[CompileError] = field(default_factory=list)
    warnings: list[CompileError] = field(default_factory=list)
    log: str = ""


def _parse_log(log_text: str) -> tuple[list[CompileError], list[CompileError]]:
    errors: list[CompileError] = []
    warnings: list[CompileError] = []

    # Match lines like: ./main.tex:45: Undefined control sequence.
    error_re = re.compile(
        r"^(?P<file>[^\n:]+\.tex):(?P<line>\d+): (?P<msg>.+)$", re.MULTILINE
    )
    # Match ! LaTeX Error: File 'foo.sty' not found. — with optional line prefix
    latex_error_re = re.compile(
        r"^! LaTeX Error: (?P<msg>.+?)(?:\.|$)", re.MULTILINE
    )
    # Match any ! <error-type> line
    bang_error_re = re.compile(
        r"^!(?: (?:Undefined control sequence|Emergency stop|I can't find file|Missing (?:\\begin|\\end|number|insert|\\right|\\left)|Extra|Paragraph ended|Display math|Infinite glue|Runaway|File not found|No pages|There's no line here|Illegal|Argument of|Too many|Capacity exceeded).*)$", re.MULTILINE
    )
    # Match the file+line context after a ! line: l.45 .... or \file.tex:123
    line_re = re.compile(r"^l\.(?P<line>\d+)\s", re.MULTILINE)
    # LaTeX Warning: ...
    warn_re = re.compile(r"^LaTeX Warning: (?P<msg>.+)$", re.MULTILINE)
    # Overfull/underfull
    box_re = re.compile(
        r"^(Overfull|Underfull) \\[hv]box.+at lines? (?P<line>\d+)", re.MULTILINE
    )
    # Package warnings
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

    # Find ! lines without associated file:line matches
    bang_lines = list(bang_error_re.finditer(log_text))
    for i, m in enumerate(bang_lines):
        # Try to find a following line number
        # Only add if not already captured by error_re above
        already_captured = any(
            m.group(0) in e.message for e in errors
        )
        if not already_captured:
            errors.append(
                CompileError(
                    file="main.tex", line=None, message=m.group(0).strip()
                )
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

    return errors, warnings


async def compile_doc(doc_path: str) -> CompileResult:
    """Compile workspace/<doc_path>/main.tex with lualatex (two passes for cross-refs)."""

    src_dir = WORKSPACE / doc_path
    main_tex = src_dir / "main.tex"

    if not main_tex.exists():
        return CompileResult(
            success=False,
            pdf_path=None,
            errors=[CompileError(file="main.tex", line=None, message="main.tex not found")],
        )

    out_dir = src_dir / ".build"
    out_dir.mkdir(exist_ok=True)

    # Use lualatex directly (latexmk requires Perl which may not be installed on Windows).
    # Two passes resolve cross-references and TikZ overlays.
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
            # Abort early on first-pass failure
            if r.returncode != 0:
                return r.returncode, "\n".join(logs)
        return 0, "\n".join(logs)

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

    if returncode == 0 and pdf_candidate.exists():
        stable_pdf = src_dir / "out.pdf"
        shutil.copy2(pdf_candidate, stable_pdf)
        return CompileResult(
            success=True, pdf_path=stable_pdf, errors=errors, warnings=warnings, log=log_text
        )
    else:
        return CompileResult(
            success=False, pdf_path=None, errors=errors, warnings=warnings, log=log_text
        )
