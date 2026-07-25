@echo off
cd /d D:\AI_Learnigns\LatexCoverLetter
git add -A
git commit -m "Phase 4: anti-hallucination guard — 20/20 tests passing

- app/guard/validator.py: 9-rule validator (JSON schema, fact_ids, focus_phrase, hook_key, banned claims, numbers, entities, length, certifications)
- app/guard/factbank.py: loads facts.yaml, indexes fact_ids/numbers/entities
- app/guard/models.py: TailorResponse, ValidationIssue/Result, FactBank dataclasses
- app/guard/rules.yaml: hook_keys, regex patterns, tolerance config
- tests/test_guard.py: 20 adversarial tests covering all 9 rules
- tests/conftest.py: self-contained test fixtures (no real facts.yaml dependency)

Bug fixes applied during review:
- Fixed _RULES_PATH case mismatch (variable scope)
- Entity regex extended to match camelCase single-word names (VxWorks, WinIDEA)
- Compound term regex now handles hyphenated standards (DO-178C)
- Rule 6 skips numbers inside ISO/DO/IEC standard names and compound terms (6-phase)
- Number normalization strips units (%/years/months) for comparison"
git push origin Phase2 2>&1
