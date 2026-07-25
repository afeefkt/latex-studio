@echo off
cd /d D:\AI_Learnigns\LatexCoverLetter
python -m pytest tests/test_guard.py -v --tb=long 2>&1
