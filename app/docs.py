from pathlib import Path

WORKSPACE = Path(__file__).parent.parent / "workspace"


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
