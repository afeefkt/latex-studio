@echo off
cd /d D:\AI_Learnigns\LatexCoverLetter
echo === GIT STATUS ===
git status
echo.
echo === GIT REMOTE ===
git remote -v
echo.
echo === GIT LOG (last 5) ===
git log --oneline -5
echo.
echo === DONE ===
