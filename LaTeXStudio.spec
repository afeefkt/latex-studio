# -*- mode: python ; coding: utf-8 -*-

# ── LaTeX Studio PyInstaller spec ──
# Build: pyinstaller LaTeXStudio.spec

import sys
from pathlib import Path

a = Analysis(
    ["app/__main__.py"],
    pathex=["."],
    binaries=[],
    datas=[
        ("app/static", "app/static"),
        ("app/llm/prompts", "app/llm/prompts"),
        ("app/guard/rules.yaml", "app/guard"),
        ("workspace/templates", "workspace/templates"),
        ("workspace/facts.example.yaml", "workspace"),
        ("workspace/hooks.example.yaml", "workspace"),
        ("workspace/i18n", "workspace/i18n"),
    ],
    hiddenimports=[
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.http.httptools_impl",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.protocols.websockets.websockets_impl",
        "uvicorn.lifespan.on",
        "uvicorn.logging",
        "app.llm.deepseek",
        "app.llm.nvidia",
        "app.llm.ollama",
        "app.llm.openrouter",
        "pydantic",
        "pydantic_core",
        "yaml",
        "certifi",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "httpx", "_pytest", "watchfiles"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LaTeXStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="LaTeXStudio",
)
