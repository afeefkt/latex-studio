# Graph Report - D:/AI_Learnigns/LatexCoverLetter  (2026-08-07)

## Corpus Check
- Corpus is ~42,763 words - fits in a single context window. You may not need a graph.

## Summary
- 708 nodes · 1391 edges · 36 communities (32 shown, 4 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 32 edges (avg confidence: 0.58)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Guard Models & Validation
- CV Content Generation
- Frontend Apply Flow
- Document Generation Pipeline
- LLM Provider Abstraction
- Fact Bank & Bullets
- CV Translation
- AI Chat & Patch Apply
- LaTeX Compilation
- API Endpoints & Profiles
- Document & Profile Management
- File & PDF Serving
- Document CRUD & Tests
- Guard Rules & Prompts
- Application Tracker
- Job Fit Scoring
- Letter Translation
- Workspace Profiles
- Generation Tests
- Frontend Document Actions
- Template & Facts Loading
- Editor & Chat UI
- Job Analysis Flow
- PDF Viewer
- Language & Template Loader
- Template Mapper
- Applications View
- Graphify Plugin
- macOS Installer
- Test Runner
- Claude Config

## God Nodes (most connected - your core abstractions)
1. `validate_tailor_response()` - 36 edges
2. `_split_skills()` - 32 edges
3. `load_factbank()` - 23 edges
4. `generate_documents()` - 18 edges
5. `TailorResponse` - 17 edges
6. `OpenAICompatProvider` - 17 edges
7. `_names()` - 17 edges
8. `apply_cv_strings()` - 16 edges
9. `load_facts()` - 16 edges
10. `FactBank` - 15 edges

## Surprising Connections (you probably didn't know these)
- `README — LaTeX Studio Project Overview` --references--> `LaTeX Studio App Plan — Architecture and Design Spec`  [INFERRED]
  README.md → LATEX_STUDIO_APP_PLAN.md
- `requirements.txt — Python dependencies` --implements--> `LaTeX Studio App Plan — Architecture and Design Spec`  [INFERRED]
  requirements.txt → LATEX_STUDIO_APP_PLAN.md
- `Apply View — 4-step job application workflow (analyse, fit check, configure, ready)` --conceptually_related_to--> `Content Mode — fact-constrained JD tailoring via guard-validated JSON output`  [INFERRED]
  app/static/index.html → LATEX_STUDIO_APP_PLAN.md
- `test_no_requirements_is_unknown()` --calls--> `score_fit()`  [EXTRACTED]
  tests/test_fit.py → app/content.py
- `test_sidebar_budget_never_collapses_to_nothing()` --calls--> `_sidebar_skill_limit()`  [EXTRACTED]
  tests/test_skills.py → app/content.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Content Safety Pipeline — facts.yaml + anti-hallucination guard + content mode form the core fact-constraint system** — latex_studio_app_plan_facts_yaml, latex_studio_app_plan_anti_hallucination_guard, latex_studio_app_plan_content_mode [EXTRACTED 1.00]
- **LLM Cost Optimization — provider abstraction + model routing + prompt caching combine to minimize cost and latency** — latex_studio_app_plan_llm_provider_abstraction, latex_studio_app_plan_model_routing, latex_studio_app_plan_prompt_cache [EXTRACTED 0.95]
- **Guard Validation Runtime — rules.yaml config + content_mode prompt + hook_keys enum form the runtime guard contract** — app_guard_rules, app_llm_prompts_content_mode, app_guard_rules_hook_keys [INFERRED 0.85]

## Communities (36 total, 4 thin omitted)

### Community 0 - "Guard Models & Validation"
Cohesion: 0.06
Nodes (71): FactBank, MatchedRequirement, BaseModel, TailorResponse, ValidationIssue, ValidationResult, _cert_patterns_for_language(), True if >=threshold fraction of meaningful phrase tokens appear in-order (not… (+63 more)

### Community 1 - "CV Content Generation"
Cohesion: 0.05
Nodes (70): _available_flags(), _curated_bars(), _distinctive(), _group_bullets_by_role(), _language_dots(), _language_rows(), _mentions(), _norm() (+62 more)

### Community 2 - "Frontend Apply Flow"
Cohesion: 0.03
Nodes (64): appLayout, appList, applyDownloads, applyModel, applyProvider, applySettingsPanel, applyStatus, applyStep2 (+56 more)

### Community 3 - "Document Generation Pipeline"
Cohesion: 0.07
Nodes (51): _build_hook_text(), _create_unique(), _cv_vars(), generate_documents(), GenerateRequest, _get_bullets_with_context(), _letter_chrome(), _letter_vars() (+43 more)

### Community 4 - "LLM Provider Abstraction"
Cohesion: 0.10
Nodes (11): ABC, _ask_llm(), Call LLM with streaming, collect full response., DeepSeekProvider, NvidiaProvider, OllamaProvider, OpenAICompatProvider, get_provider() (+3 more)

### Community 5 - "Fact Bank & Bullets"
Cohesion: 0.10
Nodes (28): _expand_role_ids_to_bullets(), _get_bullet_texts(), Expand any role-level IDs in `ids` to their constituent bullet IDs. Proper…, Look up bullet texts from facts.yaml by ID., _extract_certifications(), _extract_entities(), _extract_fact_ids(), _extract_numbers() (+20 more)

### Community 6 - "CV Translation"
Cohesion: 0.14
Nodes (28): apply_cv_strings(), collect_cv_strings(), Substitute translated strings back into a *copy* of the CV variables. `facts`…, Stable key for a role, derived from employer + start date. Positional keys…, Flatten every translatable CV string into {key: english_text}., _rkey(), Names, employers, institutions, cities, tools and emails must not be sent to a…, facts.roles and role_groups must address the same role by the same key,… (+20 more)

### Community 7 - "AI Chat & Patch Apply"
Cohesion: 0.13
Nodes (27): accept_patch(), AcceptRequest, apply_and_fix(), _apply_structured_edit(), ApplyFixRequest, chat_stream(), ChatRequest, DiffRequest (+19 more)

### Community 8 - "LaTeX Compilation"
Cohesion: 0.11
Nodes (24): compile_doc(), CompileError, CompileResult, _git_commit(), _parse_log(), Path, LaTeX compilation + git auto-commit., Resolve the active workspace root at call time. app.docs rebinds its module-… (+16 more)

### Community 9 - "API Endpoints & Profiles"
Cohesion: 0.11
Nodes (25): Write facts back to facts.yaml., save_facts(), compile_endpoint(), CompileBody, create_from_template(), create_profile_endpoint(), CreateBody, FactsBody (+17 more)

### Community 10 - "Document & Profile Management"
Cohesion: 0.15
Nodes (22): get_active_profile(), list_documents(), Return all user-editable documents in the workspace (cv/, letters/<name>/…, read_file(), get_doc(), get_doc_files(), get_documents(), get_facts() (+14 more)

### Community 11 - "File & PDF Serving"
Cohesion: 0.10
Nodes (22): api_route, _force_rmtree(), list_doc_files(), pdf_path(), Path, Render all .j2 files from a template folder into target_dir., Validate that doc_path resolves inside the workspace. Normalises separators,…, Resolve a document file path without allowing escapes from the document. (+14 more)

### Community 12 - "Document CRUD & Tests"
Cohesion: 0.13
Nodes (20): delete_document(), _ignore_assets(), shutil.copytree filter — keeps the same junk out of nested folders., _skip_asset(), fixture, parametrize, Point the module at a throwaway workspace with a base CV and one document., The git dir lives outside the document tree and was being orphaned. (+12 more)

### Community 13 - "Guard Rules & Prompts"
Cohesion: 0.15
Nodes (21): Guard Rules — hook_keys, regex patterns, tolerances, hook_keys Enum — fixed set of five pre-written letter opener keys, Content Mode LLM Prompt — JD tailoring system prompt, LaTeX Mode LLM Prompt — LaTeX editor assistant system prompt, index.html — Single-page frontend UI, Apply View — 4-step job application workflow (analyse, fit check, configure, ready), Release CI/CD Workflow, LaTeX Studio App Plan — Architecture and Design Spec (+13 more)

### Community 14 - "Application Tracker"
Cohesion: 0.18
Nodes (19): _ensure_header(), list_applications(), log_application(), Update a single field on a specific application row (0-indexed from newest)., Set cv_path on the most recent application., Idempotent column migration — widens existing CSV without data loss.…, Append a new application row to the CSV., Read all applications from CSV, newest first. (+11 more)

### Community 15 - "Job Fit Scoring"
Cohesion: 0.20
Nodes (18): Score how well the candidate fits this job. Pure Python — no LLM. A model…, score_fit(), m(), parametrize, Missing a *tool* shouldn't stop a well-matched application., High coverage but a missing certification -> gated down, and told why., Same coverage, different certainty -> different score., One matched requirement out of one, at varying confidence. (+10 more)

### Community 16 - "Letter Translation"
Cohesion: 0.18
Nodes (17): check_translation(), _normalised_numbers(), Extract numbers, strip thousand/decimal separators, sort. '3.5 years' and '3,5…, Compare original and translated text for preservation. Returns {"errors":…, _facts(), Translating 'familiar with DO-178C' → 'DO-178C-zertifiziert' must be caught at…, Translating something identical should produce no errors., A figure not in the original → error. (+9 more)

### Community 17 - "Workspace Profiles"
Cohesion: 0.17
Nodes (17): create_profile(), _doc_entry(), _ensure_default_profile(), git_commit(), _git_dir(), git_init(), git_log(), init_workspace() (+9 more)

### Community 18 - "Generation Tests"
Cohesion: 0.16
Nodes (13): patch, client(), _FakeCompileResult, fixture, CV only → letter key is null in response., security clearance' is in the fixture's banned_claims → 422., TestClient on the content router only, with a patched workspace., Using a letter template where a CV is expected → 400. (+5 more)

### Community 19 - "Frontend Document Actions"
Cohesion: 0.20
Nodes (17): deleteDocument(), deleteWorkspaceFile(), escapeHTML(), generateDocs(), loadDocList(), loadFileContent(), loadFileManager(), newFromTemplate() (+9 more)

### Community 20 - "Template & Facts Loading"
Cohesion: 0.22
Nodes (11): adapt_facts(), create_document(), list_templates(), load_facts(), _load_template_data(), Load and return the facts.yaml content. Returns {} if missing., Project facts.yaml into the canonical shape every template consumes. Instead of…, Render a template's main.tex.j2 (or main.tex) against variables. For CV… (+3 more)

### Community 21 - "Editor & Chat UI"
Cohesion: 0.22
Nodes (11): appendChatBubble(), clearChatEmpty(), createEditor(), getEditorContent(), jumpToLine(), saveCurrentFile(), scheduleCompile(), sendChatMessage() (+3 more)

### Community 22 - "Job Analysis Flow"
Cohesion: 0.36
Nodes (9): analyseJob(), cancelPrefetch(), consumeTailorStream(), renderFitReport(), resetApplyFlow(), schedulePrefetch(), setPrefetchHint(), setProgressStep() (+1 more)

### Community 23 - "PDF Viewer"
Cohesion: 0.29
Nodes (7): fitWidth(), loadPdf(), renderPage(), setStatus(), setZoom(), tryLoadPdf(), updatePageInfo()

### Community 24 - "Language & Template Loader"
Cohesion: 0.50
Nodes (5): fetchJSON(), loadLanguages(), loadTemplateList(), loadTemplates(), populateSelect()

### Community 25 - "Template Mapper"
Cohesion: 0.50
Nodes (4): loadTemplateGrid(), mapTemplate(), renderTemplateGrid(), showMapTemplatePanel()

### Community 26 - "Applications View"
Cohesion: 0.67
Nodes (3): loadApplications(), renderApplications(), toggleApplicationsView()

## Knowledge Gaps
- **69 isolated node(s):** `docFiles`, `templatesCache`, `statusBadge`, `errorList`, `pdfCanvas` (+64 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **4 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `validate_tailor_response()` connect `Guard Models & Validation` to `Document Generation Pipeline`, `Fact Bank & Bullets`?**
  _High betweenness centrality (0.089) - this node is a cross-community bridge._
- **Why does `apply_cv_strings()` connect `CV Translation` to `Document Generation Pipeline`?**
  _High betweenness centrality (0.039) - this node is a cross-community bridge._
- **Why does `_split_skills()` connect `CV Content Generation` to `Document Generation Pipeline`?**
  _High betweenness centrality (0.035) - this node is a cross-community bridge._
- **What connects `docFiles`, `templatesCache`, `statusBadge` to the rest of the system?**
  _69 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Guard Models & Validation` be split into smaller, more focused modules?**
  _Cohesion score 0.06054054054054054 - nodes in this community are weakly interconnected._
- **Should `CV Content Generation` be split into smaller, more focused modules?**
  _Cohesion score 0.05030181086519115 - nodes in this community are weakly interconnected._
- **Should `Frontend Apply Flow` be split into smaller, more focused modules?**
  _Cohesion score 0.02857142857142857 - nodes in this community are weakly interconnected._