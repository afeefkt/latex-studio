@echo off
setlocal enabledelayedexpansion
set "LOG=D:\AI_Learnigns\LatexCoverLetter\git_result.txt"
echo === INIT ===> "%LOG%"
cd /d D:\AI_Learnigns\LatexCoverLetter
git init >> "%LOG%" 2>&1
echo %errorlevel% INIT >> "%LOG%"

echo === ADD ===>> "%LOG%"
git add -A >> "%LOG%" 2>&1
echo %errorlevel% ADD >> "%LOG%"

echo === STATUS ===>> "%LOG%"
git status --short >> "%LOG%" 2>&1

echo === COMMIT ===>> "%LOG%"
git commit -m "Phase 3: Fact bank + data-driven rendering

- Added workspace/facts.yaml as single source of truth (identity, education, 4 roles with bullets+tags+tools, skills, languages, awards, hobbies, banned_claims)
- Rewrote ats-cv/main.tex.j2 to render entirely from facts via Jinja2 loops
- Created designed-cv/main.tex.j2 (FortySecondsCV) that renders from facts + copies static assets from cv/
- Added load_facts()/save_facts(), render_template(), smart create_document() with auto-facts injection
- New API routes: GET/POST /api/facts, POST /api/render
- Depends on PyYAML and jinja2 (already in requirements.txt)" >> "%LOG%" 2>&1
echo %errorlevel% COMMIT >> "%LOG%"

echo === LOG ===>> "%LOG%"
git log --oneline -3 >> "%LOG%" 2>&1

echo === DONE ===>> "%LOG%"
