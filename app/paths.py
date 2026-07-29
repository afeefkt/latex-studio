# ── Central path module — single source for all directories ──

import sys
from pathlib import Path


def _bundle_root() -> Path:
    """Directory where read-only bundled assets live."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).parent.parent


def _data_root() -> Path:
    """Writable user-data directory. Created on first run."""
    if getattr(sys, "frozen", False):
        from platformdirs import user_data_dir
        return Path(user_data_dir("LaTeXStudio", "LaTeXStudio"))
    return Path(__file__).parent.parent


BUNDLE_ROOT: Path = _bundle_root()
DATA_ROOT: Path = _data_root()

# Read-only bundled asset paths
STATIC_DIR = BUNDLE_ROOT / "app" / "static"
PROMPTS_DIR = BUNDLE_ROOT / "app" / "llm" / "prompts"
GUARD_DIR = BUNDLE_ROOT / "app" / "guard"
TEMPLATES_SRC = BUNDLE_ROOT / "workspace" / "templates"

# Writable runtime paths
WORKSPACE = DATA_ROOT / "workspace"
TEMPLATES = WORKSPACE / "templates"
DOCGIT_DIR = DATA_ROOT / ".docgit"
