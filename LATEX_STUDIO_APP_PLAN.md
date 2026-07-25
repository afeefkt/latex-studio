# Project Spec — "LaTeX Studio" (self-hosted Overleaf-style editor + LLM assistant for CV & cover letters)

**Owner:** Afeef Kallanthodan
**Status:** Planning → implementation
**Read this whole document before writing code. Implement phase by phase. Stop after each phase and show me the result.**

---

## 1. Feasibility verdict — read this first

| What you asked for | Feasible? | Notes |
|---|---|---|
| Overleaf-like editor with live PDF preview on the right | **Yes** | ~1–2 evenings for a working version. This is the easy part. |
| PDF stays sharp at any zoom, downloadable | **Yes — automatic** | LaTeX output is vector. Nothing to build. See §6. |
| Chat sidebar wired to DeepSeek / NVIDIA, edits the LaTeX | **Yes** | ~2 evenings. Provider-agnostic layer, see §7. |
| Strict anti-hallucination filtering | **Yes, but this is the real work** | ~1 weekend. Design in §8 — do not skip it. |
| Paste a whole job ad → tailored letter | **Yes** | Extraction + selection, not free generation. §8. |
| Template gallery with colourful designs | **Yes** | Sourcing plan in §9. Read the ATS warning. |
| Import existing CV PDF → base template | **Partly** | Content imports well; *visual layout* does not. §10. |
| Full Overleaf clone (multi-user, real-time collab, cloud) | **No — and don't** | You are one user. Collaboration, accounts, and hosting are 90% of Overleaf's complexity and 0% of your benefit. |

**Total realistic effort to something you use daily: 5–8 evenings.** Full scope through Phase 6: ~3 weekends.

The honest risk is not technical. It is that you spend four weekends building a tool instead of sending applications. Phase 1–3 already replaces your current workflow. Treat Phase 4+ as a portfolio project (which it is — it feeds your local-AI LinkedIn content cluster directly), not as a prerequisite for applying.

---

## 2. Scope: what this app is and is not

**It is:** a single-user, locally-hosted, browser-based LaTeX editor for exactly two document types — CV and cover letter — with a fact-constrained LLM assistant and a template gallery.

**It is not:** a general LaTeX IDE, a multi-project manager, a collaboration tool, a cloud service, or something anyone else logs into.

**Explicitly out of scope (do not build):** user accounts, authentication, real-time collaborative editing, a database, bibliography/BibTeX tooling, a mobile layout, Docker Compose orchestration for a "deployment", or a plugin system.

---

## 3. Technology decisions

### 3.1 Frontend framework — Streamlit vs FastAPI + browser JS

You asked about Streamlit. Honest comparison:

| Requirement | Streamlit | FastAPI + vanilla JS |
|---|---|---|
| Real code editor (LaTeX syntax, line numbers, autocomplete) | `streamlit-ace` — dated, limited | CodeMirror 6 — what Overleaf itself uses |
| PDF preview that keeps scroll position on recompile | Painful; iframe reloads | PDF.js, full control |
| Split-pane resizable layout | Fights the framework | Trivial CSS |
| Every keystroke re-runs the whole script | Yes — the core Streamlit model | No |
| Streaming LLM chat tokens | Workable but awkward | Native SSE |
| Effort to first working version | Lower (~1 evening) | Slightly higher (~2 evenings) |

**Decision: FastAPI backend + a static frontend (CodeMirror 6 + PDF.js + plain JS).** Streamlit's rerun model is fundamentally wrong for an editor. The extra effort is one evening and you get something that actually feels like Overleaf.

No React, no build step, no npm. Load CodeMirror and PDF.js from CDN, write the frontend as three files: `index.html`, `app.js`, `style.css`.

### 3.2 Full stack

| Layer | Choice | Reason |
|---|---|---|
| Backend | Python 3.11+, FastAPI, Uvicorn | You already know Python |
| Editor | CodeMirror 6, `@codemirror/legacy-modes/stex` | Overleaf uses CM6 |
| PDF viewer | PDF.js | Vector rendering, zoom, text selection |
| Compile | `latexmk -lualatex` via `subprocess`, `-no-shell-escape` | Safe, standard |
| Templating | Jinja2 with **custom delimiters** (§11.3) | LaTeX brace collision |
| Config/data | YAML + JSON files on disk | No database |
| Versioning | `git` per document folder, auto-commit on compile | Free undo history |
| LLM | Provider-abstracted (§7) | Never hardcode one vendor |
| Chat protocol | Server-Sent Events | Token streaming, no WebSocket complexity |

---

## 4. Architecture

```
┌──────────────────────── Browser (localhost:8000) ────────────────────────┐
│  ┌───────────────┐  ┌──────────────────┐  ┌─────────────────────────┐   │
│  │ File tree     │  │ CodeMirror 6     │  │ PDF.js preview          │   │
│  │ Templates     │  │ (main.tex,       │  │ - zoom / page nav       │   │
│  │ Fact bank     │  │  facts.yaml,     │  │ - keeps scroll on       │   │
│  │               │  │  style.sty)      │  │   recompile             │   │
│  └───────────────┘  └──────────────────┘  └─────────────────────────┘   │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │ Chat panel — "ask" / "patch" modes, diff view with Accept/Reject   │ │
│  └────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────┬───────────────────────────────────────┘
                                   │ REST + SSE
┌──────────────────────────────────▼───────────────────────────────────────┐
│ FastAPI                                                                  │
│  /api/compile ──► latexmk ──► PDF bytes + parsed error log               │
│  /api/docs     ──► filesystem CRUD                                       │
│  /api/templates ──► gallery, instantiate                                 │
│  /api/import   ──► PDF/DOCX ──► facts.yaml (§10)                         │
│  /api/llm/chat ──► LLMProvider ──► SSE stream          (read-only advice) │
│  /api/llm/tailor ──► JD + facts ──► GUARD ──► proposed patch  (§8)       │
└──────────────────────────────────┬───────────────────────────────────────┘
                                   │
              ┌────────────────────┴────────────────────┐
              │ workspace/                              │
              │   facts.yaml         ← locked truth     │
              │   cv/ main.tex, style.sty, .git         │
              │   letters/<slug>/ main.tex, job.yaml    │
              │   templates/                            │
              └─────────────────────────────────────────┘
```

---

## 5. Repository layout

```
latex-studio/
├── README.md
├── requirements.txt
├── run.sh                      # uvicorn app.main:app --reload --port 8000
├── app/
│   ├── main.py                 # FastAPI app, route registration
│   ├── compile.py              # latexmk wrapper, log parser
│   ├── docs.py                 # workspace file CRUD, git auto-commit
│   ├── templates_api.py        # gallery listing + instantiation
│   ├── importer.py             # PDF/DOCX → facts.yaml
│   ├── llm/
│   │   ├── provider.py         # abstract base + registry
│   │   ├── deepseek.py
│   │   ├── nvidia.py
│   │   ├── ollama.py
│   │   └── prompts/            # versioned prompt files, .md
│   ├── guard/
│   │   ├── factbank.py         # load + index facts.yaml
│   │   ├── validator.py        # THE anti-hallucination gate (§8)
│   │   └── rules.yaml          # allowlists, banned patterns
│   └── static/
│       ├── index.html
│       ├── app.js
│       └── style.css
├── workspace/                  # user data — gitignored from the app repo
│   ├── facts.yaml
│   ├── cv/
│   ├── letters/
│   └── templates/
└── tests/
    ├── test_guard.py           # MUST exist — see §8.6
    └── fixtures/
```

---

## 6. PDF quality — nothing to build

Your question: *"can it produce quality PDF, downloadable, sharp when zoomed, like Overleaf?"*

Yes, automatically, because it is the same mechanism:

- LaTeX emits **vector** PDF. Glyphs are outlines, rules are vectors. Zoom is infinite by construction.
- PDF.js renders from those vectors at whatever zoom you pick — the on-screen render is not the download. The download is the raw file from `latexmk`, byte-identical to what Overleaf would produce from the same source.
- **Requirement to preserve this:** fonts must be *embedded* (LuaLaTeX + `fontspec` does this) and any images you add must be vector (PDF/SVG) or ≥300 dpi. A JPEG photo in the CV sidebar is the only thing that will ever look soft — use a high-res crop.
- Verify with `pdffonts out.pdf` — every font must show `emb yes`.

---

## 7. LLM provider layer

**Never hardcode one vendor.** Define one interface, three implementations, selected by config.

```python
class LLMProvider(ABC):
    def chat(self, messages: list[dict], *, stream: bool = False,
             json_schema: dict | None = None) -> Iterator[str] | str: ...
```

All three targets speak the OpenAI wire format, so one HTTP client covers all of them — only `base_url`, `api_key`, and `model` differ.

| Provider | Base URL | Cost / limits (checked 25 Jul 2026 — reverify) | Use for |
|---|---|---|---|
| **DeepSeek** | `https://api.deepseek.com` | V4 Flash ≈ $0.14 / 1M input, $0.28 / 1M output; cache-hit input ≈ $0.003 / 1M. New accounts get a free grant (~5M tokens). | **Default.** Your whole use case is maybe 10k tokens per letter → cents per month. |
| **NVIDIA NIM** | `https://integrate.api.nvidia.com/v1` | Free developer tier, no credit card, ~40 requests/minute. Hosts DeepSeek/Llama/Qwen/Nemotron. Terms permit development/testing/evaluation, not production service. | Free fallback, and a second opinion from a different model. |
| **Ollama (local)** | `http://localhost:11434/v1` | Free, offline | Privacy-safe mode. Your CV and job ads never leave the machine. Also your LinkedIn content angle. |

Config in `.env`:

```
LLM_PROVIDER=deepseek          # deepseek | nvidia | ollama
DEEPSEEK_API_KEY=...
NVIDIA_API_KEY=...
OLLAMA_MODEL=qwen2.5:14b
MODEL_CHEAP=deepseek-v4-flash
MODEL_SMART=deepseek-v4-pro
```

### 7.1 Model routing — which task gets which model

**Do not use one model for everything.** Route by task. The rule: *mechanical work gets no model at all, extraction gets Flash, judgement gets Pro.*

| Stage | Task | Model | Why |
|---|---|---|---|
| Assembly | Building the `.tex` from selected fact IDs, filename generation, LaTeX escaping, tracker row | **None — pure Python** | Deterministic. A model here adds cost, latency, and risk for zero benefit. This is most of the pipeline. |
| Validation | The guard (§8.4) | **None — regex + set membership** | A model checking a model is not a control |
| Import | CV text/PDF → `facts.yaml` structure | **Flash** | Pure extraction, schema-constrained, you review the output anyway |
| JD parsing | Whole pasted job ad → list of discrete requirements, seniority, language, location, salary band | **Flash** | High volume, mechanical, runs on every ad you paste |
| Tailoring | Match requirements → `fact_ids`, pick `hook_key`, write `focus_phrase`, produce `unmatched_requirements` | **Pro** | This is the judgement call. Flash under-matches transferable skills — exactly the ADA-aerospace-to-avionics inference that is your whole positioning |
| Gap analysis | Feed `unmatched_requirements` into your weighted scoring rubric | **Pro** | Same reason; and it decides whether you apply at all |
| LaTeX mode chat | "Make headers navy", "why won't this compile" | **Flash** | Wrong answers just fail to compile — cheap to be wrong |
| Error explanation | Parsing an ugly `.log` into plain English | **Flash** | Mechanical |
| Second opinion *(optional)* | Re-run tailoring on a top-priority job, different provider | **Pro via NVIDIA free tier** | Free cross-check from a different serving stack on the five jobs that matter |

**Escalation rule:** always call Flash first for tailoring. Escalate to Pro automatically only when (a) fewer than 60% of JD requirements matched a `fact_id`, or (b) the guard raised any rule-7 warning, or (c) I click "Improve". Log which model produced each accepted patch, so you can check after 30 applications whether Pro is actually earning its cost.

### 7.2 Prompt-cache design — this is where the cost goes to zero

DeepSeek bills a repeated prompt *prefix* at the cache-hit rate (roughly 1–2% of the miss rate on Flash). Your prompts have a huge constant prefix: the system instructions plus `facts.yaml`. So order the messages deliberately:

```
[ system prompt        ]  ← constant, never edit mid-session
[ facts.yaml           ]  ← constant across all applications   ⟵ cache prefix
[ output JSON schema   ]  ← constant
──────────────────────────────────────────────────────────────
[ the pasted job ad    ]  ← the only part that varies
```

Put the variable content **last, always**. Never interpolate the company name into the system prompt — that breaks the prefix and you pay full rate on every call.

Practical consequence: with a ~6k-token constant prefix and a ~2k-token job ad, a tailored letter costs well under a cent on Flash and still only ~half a cent on Pro. At 10 applications a week this is noise — **so choose the model on quality grounds, never on cost.** The routing table above exists to keep latency and hallucination surface down, not to save money.

Also note the V4 family's ~1M-token context: you can paste an entire LinkedIn job page, cookie banners and "people also viewed" clutter included, without chunking. Strip it in Python anyway — junk in the prompt is junk the model can latch onto.

Add a provider dropdown in the chat panel header so you can switch mid-session. Log every call (provider, model, tokens, cost estimate) to `workspace/llm_usage.csv`.

**Note the pricing figures above will drift.** Do not embed them in code; put them in the README with the date checked.

---

## 8. The anti-hallucination system — the most important section

This is where the project succeeds or fails. A cover letter containing an invented certification is worse than no cover letter. Build the guard **before** the chat feature, not after.

### 8.1 Core principle

> **The model never states facts. It only selects, orders, and rephrases content that already exists in `facts.yaml`, plus terminology copied verbatim from the job ad.**

Generation of new factual claims is not "discouraged by prompting" — it is **structurally impossible**, because the model's output is validated against an allowlist before it can touch the document.

### 8.2 `facts.yaml` — the single source of truth

Hand-written by you once, then treated as immutable by the app. Sketch:

```yaml
identity:
  name: Afeef Kallanthodan
  location: Regensburg, Germany
  work_authorisation: EU Blue Card
  languages: [{lang: English, level: Professional}, {lang: German, level: B1 (BAMF)}]

education:
  - degree: B.Tech Mechanical Engineering
    institution: Mahatma Gandhi University
    years: "2011-2015"

certifications_held: []          # deliberately empty — see banned claims
certifications_in_progress:
  - {name: DO-178C, status: self-study, claimable_as: "familiar with the objectives of"}

roles:
  - id: koosys
    title: Embedded Software Development/Test Engineer
    org: KooSys GmbH
    location: Regensburg
    start: 2024-09
    end: present
    bullets:
      - id: koosys_foc
        text: "Developed MBD-based FOC algorithms for 6-phase IPMSM and generated AUTOSAR ASIL-B compliant code via Embedded Coder."
        tags: [mbd, motor_control, autosar, iso26262, simulink]
      - id: koosys_plant
        text: "Built a 6-phase IPMSM plant model and MIL environment for performance validation; tuned control parameters on MIL and real hardware."
        tags: [simulation, plant_model, mil, control]
      # ... one entry per real bullet, each with an id and tags
  - id: ada
    title: Aerospace Systems Engineer
    org: Aeronautical Development Agency
    # ...

skills:
  expert:     [AUTOSAR Classic, Embedded C, MATLAB/Simulink, Stateflow, CANoe, Python, MIL/SIL/HIL]
  proficient: [ISO 26262 ASIL-B, CppUTest, Helix QAC, TESSY, DOORS, Polarion, XCP, Simscape, Catia V5]
  familiar:   [C#, Java, CAPL, Embedded Coder autocoding toolchain evaluation]

banned_claims:                   # hard block, any casing, any phrasing
  - ISTQB
  - DO-178C certified
  - DO-254
  - security clearance
  - Sicherheitsüberprüfung
  - PhD
  - Master's degree
  - team lead
  - managed a team
  - Yocto
  - Embedded Linux
  - ITAR
```

### 8.3 What the model is allowed to produce — constrained output

The tailoring call must return **JSON matching a schema**, never free prose:

```json
{
  "matched_requirements": [
    {"jd_phrase": "model-based development in Simulink",
     "fact_ids": ["koosys_foc", "tata_mbd"],
     "confidence": 0.9}
  ],
  "selected_bullet_ids": ["koosys_foc", "koosys_plant", "ada_dynamics"],
  "focus_phrase": "satellite simulator software",
  "hook_key": "rare_combination",
  "unmatched_requirements": ["DO-254 hardware assurance", "VxWorks"],
  "notes_for_human": "JD requires 5 yrs avionics; strongest angle is ADA + ISO 26262 transfer."
}
```

Note what this buys you:

- `selected_bullet_ids` → the letter body is assembled from **verbatim `facts.yaml` strings**. Zero generation.
- `focus_phrase` → must be a substring of the pasted job ad (validated, §8.4).
- `hook_key` → must be one of a fixed enum of pre-written openers.
- `unmatched_requirements` → this is the **honest gap list**, and it is genuinely useful: it feeds straight into your existing job-scoring rubric.

Use structured-output / JSON mode where the provider supports it; otherwise instruct JSON-only and parse strictly, retrying once on parse failure, then failing loudly.

### 8.4 The validator — `app/guard/validator.py`

Every LLM output passes through this before it can be inserted. Any failure = reject and show me why. **Never silently repair.**

| # | Check | Action on failure |
|---|---|---|
| 1 | Output parses as JSON against the schema | Retry once, then hard fail |
| 2 | Every `fact_id` exists in `facts.yaml` | Hard fail (this catches invented experience) |
| 3 | `focus_phrase` appears as a substring of the job-ad text (case-insensitive, whitespace-normalised) | Hard fail |
| 4 | `hook_key` in the fixed enum | Hard fail |
| 5 | Assembled letter text contains **no** string from `banned_claims` | Hard fail, name the offending term |
| 6 | Every **number, year, duration, and percentage** in the final text appears in `facts.yaml` | Hard fail — flag the specific token |
| 7 | Every **capitalised multi-word entity** (tool, standard, company) in the final text appears in `facts.yaml` **or** in the job ad | Warn + highlight in the diff for manual confirmation |
| 8 | Final text length within ±20% of the reference letter | Warn |
| 9 | Nothing claims a certification, clearance, or degree not in `facts.yaml` | Hard fail |

Implement #6 and #7 with plain regex + set membership. **No LLM in the validator** — a model checking a model is not a control.

### 8.5 Human-in-the-loop gate

- The chat panel **never writes to the editor directly.** It produces a proposed patch.
- Show it as a side-by-side or inline **diff** with `Accept` / `Reject` / `Accept and edit` buttons.
- Any line touching a factual claim (validator rule 7 warnings) is highlighted amber and requires an explicit confirm click.
- Nothing compiles into a downloadable PDF while a `TODO:` or `DRAFT:` marker remains in the source — block the export button, not the compile.

### 8.6 Tests — non-negotiable

`tests/test_guard.py` must contain, at minimum, adversarial fixtures where the model output:

1. invents a fact_id
2. claims ISTQB certification
3. claims "7 years of avionics experience"
4. invents a tool ("developed in VxWorks")
5. copies a `focus_phrase` not present in the JD
6. writes a plausible-but-false number ("reduced test time by 40%")

Each must be **rejected**. Wire these into a `pytest` run and do not proceed to Phase 5 until they all pass. If you cannot break your own guard in six tries, write six more.

### 8.7 Structural lock — why the format is identical for every company

The layout is not "usually the same" — it is **structurally incapable of varying**, because no model ever produces LaTeX in Content mode.

| Artefact | Who writes it | Varies per company? |
|---|---|---|
| `template/letter.tex.j2` — preamble, `scrlttr2` setup, fonts, margins, spacing, sign-off | You, once | **Never** |
| `style.sty` — colours, section formatting | You, once | **Never** |
| Evidence paragraphs | `facts.yaml`, verbatim | Only *which* are selected |
| Recipient, subject, `focus_phrase`, `hook_key` | Job YAML, filled from validated JSON | Yes — these four zones only |
| The final `.tex` | **Python + Jinja2** | Assembled, never generated |

The model's entire output is a JSON object of IDs and one short phrase. Python renders it through the same template every time, so two letters to two different companies differ only in the four zones — byte-identical everywhere else. Diff any two output `.tex` files as a test; if anything outside the four zones differs, that is a bug.

Enforce it mechanically: in Content mode, `template/` and `style.sty` are **not in the writable file set**. Only LaTeX mode can touch them, and LaTeX mode never sees `facts.yaml`. When you do change the template, it changes for all future letters at once — which is the point.

### 8.8 Chat modes

Two modes, clearly separated in the UI:

| Mode | Can it touch facts? | Can it edit the document? |
|---|---|---|
| **LaTeX mode** | No — it never sees `facts.yaml` | Yes, freely. This is for *code*: "make the section headers dark blue", "fix this alignment error", "why won't this compile". No hallucination risk that matters, because a wrong LaTeX suggestion just fails to compile. |
| **Content mode** | Read-only, via the guard | Only via validated patch + your Accept click |

This separation is the whole design. Let the model be free with markup; keep it on a leash with facts.

---

## 9. Templates — where to get them, and a warning

### 9.1 Sources

| Source | What's there | Licence note |
|---|---|---|
| **CTAN** (`ctan.org`) | `moderncv`, `europasscv`, `scrlttr2`, `altacv` | Mostly LPPL 1.3c — free to use and modify |
| **Awesome-CV** (GitHub, posquit0) | Clean, professional, widely used; includes a matching cover letter | Check repo LICENSE |
| **AltaCV** (GitHub, liantze) | Two-column with sidebar, colour accents, skill bars — **closest to your current CV design** | LPPL 1.3c |
| **Twenty Seconds CV** / **Deedy-Resume** | Colourful, infographic-style | Varies; Deedy is permissive |
| **Overleaf gallery** (`overleaf.com/latex/templates`) | Hundreds, filterable by CV/letter | **Per-template licence — check each** |
| **LaTeXTemplates.com** | Curated, licence stated per template | Mixed CC-BY / LPPL |

**Process:** clone 4–6 into `workspace/templates/<name>/`, each with `template.json` (display name, preview PNG, required variables, licence, source URL). The gallery reads that folder. Keep a `LICENSES.md` at the repo root listing what you used and under what terms — this matters if you ever put the app on GitHub, which you should, because it is good portfolio material.

### 9.2 The warning you need to hear

You asked for "very interesting colourful". Two conflicting goals:

| Channel | Best template |
|---|---|
| Direct upload to a company career portal (Airbus, Liebherr, Lufthansa Technik) — parsed by an ATS | **Single column, no sidebar, no skill bars, no photo-in-a-column, standard section headings.** Two-column layouts are the single most common cause of mangled ATS parsing. |
| Email to a hiring manager, recruiter contact, portfolio site, PDF you hand over in person | Colourful two-column is fine and looks good |

Your current CV is a two-column sidebar design — attractive, but it is a real ATS risk on portal submissions, and ATS risk is already a field in your job-scoring rubric.

**Therefore: the app must maintain both, from one `facts.yaml`.** One fact bank → two renderers → `cv_ats.pdf` and `cv_designed.pdf`. Build the ATS-safe one first; it is simpler and it is the one you send more often.

---

## 10. Importing an existing CV

Realistic expectations:

- **Content extraction: good.** `pdfplumber` for text, `python-docx` for Word. Then one LLM call whose *only* job is to structure that text into the `facts.yaml` schema — an extraction task, low hallucination risk, and you review the YAML by hand afterwards. That review is mandatory: mark the file `verified: true` and refuse to build until you have.
- **Visual layout reconstruction: do not attempt.** Reverse-engineering a PDF into equivalent LaTeX is a research problem and will waste a weekend. Import the *content*, then pick a template.
- Two-column PDFs extract in a jumbled reading order. Handle it: show extracted text side-by-side with the YAML in the import screen so you can fix ordering manually.

You already have `Afeef_Work_Experience_Updatted.txt` — that is a cleaner import source than any PDF. Use it as the Phase 3 test fixture.

---

## 11. Implementation notes that will bite you

### 11.1 Compile safety
`latexmk -lualatex -interaction=nonstopmode -halt-on-error -no-shell-escape -outdir=<tmp>`. `-no-shell-escape` is mandatory: without it, LaTeX source can execute arbitrary shell commands, and you are about to paste text from the internet into this app.

### 11.2 Compile UX
- Debounced auto-compile 1200 ms after last keystroke, plus `Ctrl+Enter` for immediate.
- **Preserve the PDF scroll position across recompiles.** Overleaf does; without it the app is unusable. Store page + scroll offset before swap, restore after.
- Parse the `.log` into structured errors (file, line, message) and make each clickable → jump to that line in the editor.
- Cancel an in-flight compile when a new one starts.

### 11.3 Jinja2 delimiters (copy verbatim)

```python
env = jinja2.Environment(
    block_start_string='\\BLOCK{', block_end_string='}',
    variable_start_string='\\VAR{', variable_end_string='}',
    comment_start_string='\\#{', comment_end_string='}',
    trim_blocks=True, autoescape=False,
    loader=jinja2.FileSystemLoader('workspace/templates'),
)
```

Register a `tex_escape` filter for `& % $ # _ { } ~ ^ \` and apply it to **every** value coming from YAML or a job ad. Real job titles contain `&` ("Simulation & Software Engineer") — this will break on day one otherwise.

### 11.4 Misc
- Auto `git commit` in the document folder on every successful compile → free version history, and a "restore previous version" button is then trivial.
- Never send `facts.yaml` to a hosted API in LaTeX-mode chat. Only Content mode, only the fields needed.
- Add an "offline mode" toggle that forces the Ollama provider — use it for anything you'd rather not upload.

---

## 12. Phases

Stop after each. Show me a working demo before moving on.

| Phase | Deliverable | Done when | Effort |
|---|---|---|---|
| **P0** | Environment check: `lualatex --version`, `kpsewhich scrlttr2.cls`, `latexmk -v`. FastAPI skeleton serving a static page. | `curl localhost:8000/api/health` returns OK | 1 h |
| **P1** | **Editor + compile + preview.** Single hardcoded document. CodeMirror left, PDF.js right, Ctrl+Enter compiles, errors listed below the editor. | I can edit `main.tex`, hit compile, see the PDF, download it | 1 evening |
| **P2** | **Workspace + templates.** File tree, multiple documents, template gallery with 3 templates (1 ATS-safe CV, 1 designed CV, 1 `scrlttr2` letter), "New from template". Git auto-commit. | I can create a new letter from a template in 3 clicks | 1 evening |
| **P3** | **Fact bank + rendering.** `facts.yaml` written and verified; ATS CV renders from it; importer turns `Afeef_Work_Experience_Updatted.txt` into a draft `facts.yaml`. | Both CV variants build from one fact bank | 1 evening |
| **P4** | **The guard, standalone.** `validator.py` + `rules.yaml` + all six adversarial tests in §8.6 passing. **No LLM wired up yet.** | `pytest` green, and I have tried and failed to sneak a false claim past it | 1 evening |
| **P5** | **LLM chat, LaTeX mode only.** Provider abstraction, all three backends, SSE streaming, provider dropdown, usage log. Can suggest LaTeX edits via diff + Accept/Reject. | I can ask "make headers navy" and accept the patch | 1 evening |
| **P6** | **Content mode / JD tailoring.** Paste job ad → structured JSON → guard → proposed letter → diff → Accept. Unmatched-requirements list shown separately. | A real Hamburg job ad produces a compilable, factually clean letter in under 60 seconds | 1 weekend |
| **P7** *(optional)* | Polish: SyncTeX click-to-source, keyboard shortcuts, export to your applications tracker CSV, dark mode | — | as desired |

**You have a genuinely useful tool at the end of P3, and your current manual workflow is fully replaced at P6.**

---

## 13. Risks

| Risk | Mitigation |
|---|---|
| Building the tool replaces doing the job search | Timebox to evenings; P1–P3 first; keep applying with the existing Word file meanwhile |
| A hallucinated claim reaches a recruiter | §8 guard, built before the LLM, with adversarial tests |
| Colourful template fails ATS parsing at Airbus | Dual output, ATS-safe is the default for portal submissions |
| Free NVIDIA tier changes or rate-limits | Provider abstraction; DeepSeek costs cents; Ollama always works offline |
| Job-ad text is pasted into a hosted API | Offline mode toggle; note that job ads are public text, but your `facts.yaml` is not |
| Template licence issues if published | `LICENSES.md`, check each repo before including |
| LuaLaTeX font not found on the machine | P0 environment check must fail loudly with the exact package to install, never silently fall back |

---

## 14. Questions to ask me before you start

1. Which OS am I developing on, and is TeX Live already installed?
2. Do I want the app to keep my current CV design (two-column, sidebar, photo), or start from AltaCV and restyle?
3. DeepSeek key, NVIDIA key, or Ollama-only for the first working version?
4. Should the letter and CV share a colour/typography theme file, or stay independent?

---

## 15. First command

Start with **P0 and P1 only.** Do not scaffold the LLM layer, the guard, or the template gallery yet. I want to see a PDF appear next to an editor before anything else exists.
