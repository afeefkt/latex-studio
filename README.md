# LaTeX Studio

A self-hosted, browser-based LaTeX editor for CV and cover letter production, with an LLM assistant that reads job ads, scores fit, tailors bullet selection, and assembles documents — constrained to facts you provide so it can never invent claims.

---

## What it does

1. **Paste a job ad** → the LLM parses it, extracts 12–20 requirements, and matches them against your `facts.yaml`
2. **Fit score** — STRONG / STRETCH / SKIP with a plain-English reason and hard-gap detection (certification, education, language)
3. **Editable letter preview** — assembled body appears in a textarea; your edits pass through the anti-hallucination guard before generating
4. **Choose a channel** — *Company portal* (ATS-safe single column) or *Email / recruiter* (designed two-column), each with its own template picker
5. **One-click compile** → named PDF downloads (`Afeef_Kallanthodan_CV_Vibracoustic.pdf`) and an entry logged to the application tracker
6. **Local profiles** — separate `workspace/<profile>/` directories for different CV personas (aerospace vs. embedded, etc.)
7. **AI template mapping** — paste any `.tex` template found online; the AI writes the Jinja adapter that renders from your fact bank

---

## Prerequisites

| Dependency | Version | Notes |
|---|---|---|
| Python | 3.12+ | |
| XeLaTeX | any recent TeX Live | `xelatex` must be on PATH |
| Font Awesome 5 | via TeX Live | `texlive-fonts-extra` or equivalent |
| LLM API key | DeepSeek / NVIDIA NIM / OpenAI | one key is enough |

---

## Setup

**1. Clone and install Python deps**

```bash
git clone https://github.com/afeefkt/latex-studio.git
cd latex-studio
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

**2. Create your `.env`**

```env
LLM_PROVIDER=deepseek          # deepseek | nvidia | openai
DEEPSEEK_API_KEY=sk-...
# NVIDIA_API_KEY=...
# OPENAI_API_KEY=...
```

**3. Create your `workspace/facts.yaml`**

Copy `workspace/facts.example.yaml` and fill in your real data. This file is gitignored — it never leaves your machine.

```bash
copy workspace\facts.example.yaml workspace\facts.yaml
```

Edit `workspace/facts.yaml` with your identity, work history (with bullet IDs), skills, education, and languages. Add any claims you must never make to `banned_claims`.

Optionally create `workspace/hooks.yaml` from `workspace/hooks.example.yaml` for custom opening hook paragraphs.

---

## Run

```bash
python -m uvicorn app.main:app --reload --port 8000
```

Or on Windows:

```
run.bat
```

Open **http://localhost:8000** in your browser.

---

## Workflow

```
Apply tab → paste job ad → Analyse Job
         → fit score + requirement breakdown
         → edit letter preview (guard-checked)
         → pick channel + template
         → compile → download PDFs
         → logged to tracker (📊)
```

The **Edit tab** gives you the raw LaTeX editor with a live PDF preview, a LaTeX chat assistant, and the AI template mapper.

---

## Templates

| ID | Name | Channel | Layout |
|---|---|---|---|
| `ats-cv` | ATS CV | Portal | Single column |
| `optimized-cv` | Optimised CV | Email | Two-column (FortySecondsCV) |
| `designed-cv` | Designed CV | Email | Two-column (FortySecondsCV) |
| `modern-cv` | Modern CV | Either | scrartcl with colour accents |
| `scrlttr2-letter` | Cover Letter | — | KOMA-Script scrlttr2 |

To add a template: create `workspace/templates/<id>/main.tex.j2` and `template.json`. See existing templates for the variable contract (`role_groups`, `matched_skills`, `facts`, etc.).

**Optional profile photo** — add `photo: "pics/PIC_SQR.png"` to `facts.identity` and place the file at `workspace/templates/<template-id>/pics/PIC_SQR.png`.

---

## Tests

```bash
python -m pytest tests/ -q
```

33 tests: 20 guard (anti-hallucination rules) + 13 fit scorer.

---

## Privacy

`workspace/` is gitignored except `workspace/templates/`. Your `facts.yaml`, generated CVs, application tracker CSV, and profile data never appear in git history. Only template files and example stubs are tracked.

---

## Third-party licenses

See [LICENSES.md](LICENSES.md).
