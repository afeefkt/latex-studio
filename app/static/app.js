// ── CodeMirror 6 via esm.sh ──────────────────────────────────────────────────
import { EditorView, basicSetup } from "https://esm.sh/codemirror@6.0.1";
import { EditorState }            from "https://esm.sh/@codemirror/state@^6.0.0?target=es2022";
import { keymap }                 from "https://esm.sh/@codemirror/view@^6.0.0?target=es2022";
import { defaultKeymap, indentWithTab, undo, redo } from "https://esm.sh/@codemirror/commands@^6.0.0?target=es2022";
import { oneDark }                from "https://esm.sh/@codemirror/theme-one-dark@^6.0.0?target=es2022";
import { StreamLanguage }         from "https://esm.sh/@codemirror/language@^6.0.0?target=es2022";
import { stex }                   from "https://esm.sh/@codemirror/legacy-modes/mode/stex?target=es2022";

// ── PDF.js ────────────────────────────────────────────────────────────────────
const PDFJS_CDN = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.4.168";
const { getDocument, GlobalWorkerOptions } = await import(`${PDFJS_CDN}/pdf.min.mjs`);
GlobalWorkerOptions.workerSrc = `${PDFJS_CDN}/pdf.worker.min.mjs`;

// ── State ─────────────────────────────────────────────────────────────────────
let currentDoc   = null;          // { path, name, kind }
let currentFile  = "main.tex";    // active file in editor
let docFiles     = [];            // files available in current doc
let factsLoadFailed = false;      // true if facts.yaml failed to load — blocks save
let pdfDoc       = null;
let currentPage  = 1;
let zoomScale    = 1.2;
let renderTask   = null;
let debounceTimer = null;
const DEBOUNCE_MS = 1200;
let savedScrollTop  = 0;
let savedScrollLeft = 0;
let cmView        = null;          // CodeMirror EditorView instance
let sidebarVisible = true;

// ── DOM refs ──────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const statusBadge    = $("status-badge");
const errorList      = $("error-list");
const pdfCanvas      = $("pdf-canvas");
const pdfScroll      = $("pdf-scroll-container");
const pdfPlaceholder = $("pdf-placeholder");
const pageInfo       = $("page-info");
const zoomLabel      = $("zoom-label");
const docLabel       = $("doc-label");
const btnDownload    = $("btn-download");
const docList        = $("doc-list");
const fileTabs       = $("file-tabs");
const editorPane    = $("editor-pane");
const workspaceEl   = $("workspace");
const sidebar       = $("sidebar");
const modalOverlay   = $("modal-overlay");
const templateGrid   = $("template-grid");
const newDocName     = $("new-doc-name");
const modalCreate    = $("modal-create");
const modalError     = $("modal-error");
const importTextarea = $("import-textarea");
const importPanel    = $("import-panel");
const modalImportBtn = $("modal-import-btn");

// Chat DOM refs
const chatMessages   = $("chat-messages");
const chatInput      = $("chat-input");
const chatProvider   = $("chat-provider");
const btnChatSend    = $("btn-chat-send");
const btnChatClear   = $("btn-chat-clear");
const chatResizeHandle = $("chat-resize-handle");
const chatPanel      = $("chat-panel");

const chatModel     = $("chat-model");
const tailorResults = $("tailor-results");

// Apply view DOM refs
const applyView      = $("apply-view");
const appLayout      = $("app-layout");
const btnViewApply   = $("btn-view-apply");
const btnViewEdit    = $("btn-view-edit");
const jdTextarea     = $("jd-textarea");
const applyProvider  = $("apply-provider");
const applyModel     = $("apply-model");
const btnAnalyse     = $("btn-analyse");
const btnApplyReset    = $("btn-apply-reset");
const btnApplySettings = $("btn-apply-settings");
const applySettingsPanel = $("apply-settings-panel");
const applyStatus    = $("apply-status");
const prefetchHint   = $("prefetch-hint");
const fitReport      = $("fit-report");
const applyStep2     = $("apply-step-2");
const applyStep3     = $("apply-step-3");
const applyStep4     = $("apply-step-4");
const generateStatus = $("generate-status");
const applyDownloads = $("apply-downloads");
const btnGenerate    = $("btn-generate");
const optCvTemplate  = $("opt-cv-template");
const optLetterTemplate = $("opt-letter-template");
const optLanguage    = $("opt-language");
const docLetter      = $("doc-letter");
const docCv          = $("doc-cv");

let chatHistory = [];
let isStreaming = false;
let chatAbortController = null;
let tailorResultData = null;

// Applications view refs
const appView = $("applications-view");
const appList = $("applications-list");

// ── CodeMirror setup ──────────────────────────────────────────────────────────

function createEditor(doc = "") {
  const compileKeymap = keymap.of([
    { key: "Ctrl-Enter", run() { triggerCompile(); return true; } },
    { key: "Mod-Enter",  run() { triggerCompile(); return true; } },
  ]);

  return new EditorView({
    state: EditorState.create({
      doc: doc,
      extensions: [
        basicSetup,
        oneDark,
        StreamLanguage.define(stex),
        keymap.of([...defaultKeymap, indentWithTab]),
        compileKeymap,
        EditorView.updateListener.of((update) => {
          if (update.docChanged && currentDoc) scheduleCompile();
        }),
        EditorView.theme({
          "&": { height: "100%", fontSize: "13px" },
          ".cm-scroller": { fontFamily: "'Cascadia Code','Fira Code','Consolas',monospace", overflow: "auto" },
          ".cm-content": { paddingBottom: "40px" },
        }),
      ],
    }),
    parent: $("editor-container"),
  });
}

function getEditorContent() {
  return cmView ? cmView.state.doc.toString() : "";
}

function setEditorContent(text) {
  if (!cmView) return;
  cmView.dispatch({
    changes: { from: 0, to: cmView.state.doc.length, insert: text },
  });
}

cmView = createEditor("");
$("editor-container").style.height = "100%";

// ── Undo/Redo buttons ─────────────────────────────────────────────────────────

$("btn-undo").addEventListener("click", () => {
  if (cmView) undo(cmView);
  cmView?.focus();
});
$("btn-redo").addEventListener("click", () => {
  if (cmView) redo(cmView);
  cmView?.focus();
});

// ── Sidebar: Document list ───────────────────────────────────────────────────

async function loadDocList() {
  try {
    const resp = await fetch("/api/docs");
    const data = await resp.json();
    renderDocList(data.documents);
  } catch (e) {
    docList.innerHTML = '<div class="sidebar-empty">Could not load documents</div>';
  }
}

async function newFromTemplate(tplId, kind) {
  const base = kind === "letter" ? "new-letter" : "new-cv";
  const name = prompt(`Name for this ${kind === "letter" ? "letter" : "CV"}? (e.g. my-app)`, base);
  if (!name || !name.trim()) return;

  try {
    const resp = await fetch(`/api/templates/${tplId}/create`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name.trim(), template_id: tplId }),
    });
    if (!resp.ok) throw new Error((await resp.json()).detail || `HTTP ${resp.status}`);
    const data = await resp.json();
    await loadDocList();
    await switchDocument(data.document.path, data.document.kind);
  } catch (e) {
    alert(`Failed to create: ${e.message}`);
  }
}

function renderDocList(docs) {
  if (!docs) return;
  if (!docs.length) {
    docList.innerHTML = '<div class="sidebar-empty">No documents yet.</div>';
    return;
  }

  const manualCVs = docs.filter(d => d.kind === "cv" && !d.generated);
  const generatedCVs = docs.filter(d => d.kind === "cv" && d.generated);
  const letters = docs.filter(d => d.kind === "letter");

  const _icon = d => d.kind === "letter" ? "✉️" : "📄";
  const _del = d => d.path === "cv" ? "" :
    `<button class="doc-delete" data-del="${escapeHTML(d.path)}" title="Delete ${escapeHTML(d.name)}">×</button>`;

  // Derive a compact role hint: strip company slug prefix and number suffix from doc name
  const _roleHint = d => {
    if (!d.company) return d.name;
    // Name format is "Tailored Company-Name-Role-Title-12" or "Cv Company-Name-..."
    // Strip leading "Cv " or "Tailored " prefix (space-separated, case-insensitive)
    let hint = d.name.replace(/^(cv|tailored)\s+/i, "");
    // Strip the company name slug (hyphens) from the front
    const companySlug = d.company.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
    hint = hint.replace(new RegExp(`^${companySlug}[-\\s]?`, "i"), "");
    // Keep trailing number suffix for disambiguation (e.g. -12 → " ·12")
    hint = hint.replace(/-(\d+)$/, " ·$1").replace(/-/g, " ").trim();
    return hint || d.name;
  };

  const _row = d => {
    const active = currentDoc && currentDoc.path === d.path ? " active" : "";
    let langBadge = "";
    if (d.language && d.language !== "en") {
      langBadge = `<span class="doc-lang">${escapeHTML(d.language.toUpperCase())}</span>`;
    }
    // For documents with a company, show company prominently + role hint below
    let nameHtml;
    if (d.company) {
      nameHtml = `<span class="doc-name-wrap">
        <span class="doc-primary">${escapeHTML(d.company)}</span>
        <span class="doc-secondary">${escapeHTML(_roleHint(d))}</span>
      </span>`;
    } else {
      nameHtml = `<span class="doc-name">${escapeHTML(d.name)}</span>`;
    }
    return `<div class="doc-item${active}" data-path="${escapeHTML(d.path)}" data-kind="${d.kind}" title="${escapeHTML(d.name)}">
      <span class="doc-icon">${_icon(d)}</span>
      ${nameHtml}
      ${langBadge}
      ${_del(d)}
    </div>`;
  };

  // Collapsed state: "generated-cvs" starts collapsed; others default to open
  function _section(key, title, items) {
    if (!items.length) return "";
    const stored = localStorage.getItem("section-collapsed-" + key);
    const collapsed = stored !== null ? stored === "1" : (key === "generated-cvs");
    const chevron = collapsed ? "▸" : "▾";
    return `<div class="doc-section">
      <div class="doc-section-header doc-section-toggle" data-section="${key}">
        <span class="section-chevron${collapsed ? ' collapsed' : ''}">${chevron}</span>
        ${title} <span class="doc-section-count">${items.length}</span>
      </div>
      <div class="doc-section-body${collapsed ? ' collapsed' : ''}">
        ${items.map(_row).join("")}
      </div>
    </div>`;
  }

  // Section order reflects the primary workflow
  let html = _section("cover-letters", "✉️ Cover Letters", letters) +
             _section("custom-cvs", "📂 Custom CVs", manualCVs) +
             _section("generated-cvs", "🤖 Generated CVs", generatedCVs);

  // Fact Bank entry
  const factsActive = currentDoc && currentDoc.path === "facts" ? " active" : "";
  html += `<div class="doc-item doc-item-facts${factsActive}" data-path="facts" data-kind="facts">
    <span class="doc-icon">📋</span>
    <span class="doc-name">Fact Bank</span>
  </div>`;

  docList.innerHTML = html;

  // Section toggle handlers
  docList.querySelectorAll(".doc-section-toggle").forEach(hdr => {
    hdr.addEventListener("click", () => {
      const key = hdr.dataset.section;
      const body = hdr.nextElementSibling;
      const chevron = hdr.querySelector(".section-chevron");
      const isCollapsed = body.classList.toggle("collapsed");
      chevron.classList.toggle("collapsed", isCollapsed);
      chevron.textContent = isCollapsed ? "▸" : "▾";
      localStorage.setItem("section-collapsed-" + key, isCollapsed ? "1" : "0");
    });
  });

  // Doc item click handlers
  docList.querySelectorAll(".doc-item").forEach(el => {
    el.addEventListener("click", () => switchDocument(el.dataset.path, el.dataset.kind));
  });
  docList.querySelectorAll(".doc-delete").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      deleteDocument(btn.dataset.del, btn);
    });
  });
}

// ── Sidebar search filter ─────────────────────────────────────────────────────
const sidebarSearch = document.getElementById("sidebar-search");
if (sidebarSearch) {
  sidebarSearch.addEventListener("input", () => {
    const q = sidebarSearch.value.toLowerCase().trim();
    docList.querySelectorAll(".doc-item").forEach(el => {
      const text = (el.title + " " + el.textContent).toLowerCase();
      el.style.display = (!q || text.includes(q)) ? "" : "none";
    });
    // Auto-expand sections that have a match when filtering
    docList.querySelectorAll(".doc-section").forEach(sec => {
      if (!q) return;
      const body = sec.querySelector(".doc-section-body");
      if (!body) return;
      const hasVisible = [...body.querySelectorAll(".doc-item")].some(el => el.style.display !== "none");
      if (hasVisible) body.classList.remove("collapsed");
    });
  });
}

async function deleteDocument(path, btn) {
  const msg = `Delete "${path}"?\n\n`
    + "The document folder and its version history are removed. This cannot be undone.";
  if (!confirm(msg)) return;

  btn.disabled = true;
  try {
    // doc_path is a :path route param, so slashes in letter paths must stay raw.
    const resp = await fetch(`/api/docs/${path}`, { method: "DELETE" });
    if (!resp.ok) {
      let detail = `HTTP ${resp.status}`;
      try { detail = (await resp.json()).detail || detail; } catch (_) {}
      alert(`Could not delete:\n\n${detail}`);
      btn.disabled = false;
      return;
    }

    // Editing a folder that no longer exists would fail on the next save.
    const wasOpen = currentDoc && currentDoc.path === path;
    if (wasOpen) {
      currentDoc = null;
      currentFile = null;
      fileTabs.innerHTML = "";
    }
    await loadDocList();
    if (wasOpen) await switchDocument("cv", "cv");
  } catch (e) {
    alert("Network error while deleting. Try again.");
    btn.disabled = false;
  }
}

// ── Document switching ────────────────────────────────────────────────────────

async function switchDocument(path, kind) {
  if (currentDoc && currentDoc.path === path) return;

  if (currentDoc && currentFile) {
    await saveCurrentFile();
  }

  // Handle Fact Bank pseudo-document
  if (path === "facts") {
    currentDoc = { path: "facts", kind: "facts", name: "Fact Bank" };
    currentFile = "facts.yaml";
    docLabel.textContent = "Fact Bank";
    docFiles = [];
    renderFileTabs();
    fileTabs.innerHTML = "";

    try {
      const resp = await fetch("/api/facts/raw");
      if (!resp.ok) {
        // Never put an error body in the buffer: saving would write it back as
        // facts.yaml, and a JSON error payload parses as valid YAML.
        factsLoadFailed = true;
        setEditorContent(`# Could not load facts.yaml (HTTP ${resp.status}).\n# Saving is disabled until it loads. Fix the file on disk, then reopen.`);
      } else {
        factsLoadFailed = false;
        setEditorContent(await resp.text());
      }
    } catch (e) {
      factsLoadFailed = true;
      setEditorContent("# Could not load facts.yaml. Saving is disabled until it loads.");
    }

    docList.querySelectorAll(".doc-item").forEach(el => {
      el.classList.toggle("active", el.dataset.path === path);
    });
    btnDownload.style.display = "none";
    pdfPlaceholder.classList.remove("hidden");
    return;
  }

  currentDoc = { path, kind, name: path.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase()) };
  currentFile = "main.tex";
  docLabel.textContent = `${currentDoc.path} / ${currentFile}`;

  // Update sidebar highlight
  docList.querySelectorAll(".doc-item").forEach(el => {
    el.classList.toggle("active", el.dataset.path === path);
  });

  // Refresh the file manager if it's visible
  const fm = document.getElementById("file-manager-panel");
  if (fm && !fm.classList.contains("hidden")) loadFileManager();

  // Load file list
  try {
    const resp = await fetch(`/api/docs/${path}/files`);
    const data = await resp.json();
    const rawFiles = data.files || [];
    docFiles = rawFiles.map(f => typeof f === "string" ? f : f.name);
    if (!docFiles.includes("main.tex")) docFiles.unshift("main.tex");
  } catch {
    docFiles = ["main.tex"];
  }
  renderFileTabs();

  // Load file content
  await loadFileContent(currentFile);

  // Load PDF if available
  await tryLoadPdf();

  // Update download link. Use the last path segment, not the whole path — a doc at
  // "letters/tailored_acme-engineer" must not download as "letters_tailored_....pdf".
  btnDownload.href = `/api/pdf/${path}`;
  btnDownload.download = `${path.split("/").pop().replace(/^(tailored_|cv_)/, "")}.pdf`;
  btnDownload.style.display = "inline-block";
}

// ── File tabs ─────────────────────────────────────────────────────────────────

function renderFileTabs() {
  if (!docFiles.length) {
    fileTabs.innerHTML = "";
    return;
  }
  const extIcons = { ".tex": "📝", ".sty": "🎨", ".cls": "📦", ".yaml": "⚙️", ".json": "{}" };
  fileTabs.innerHTML = docFiles.map(f => {
    const ext = f.substring(f.lastIndexOf("."));
    const icon = extIcons[ext] || "📄";
    const active = f === currentFile ? " active" : "";
    return `<button class="file-tab${active}" data-file="${f}">${icon} ${f}</button>`;
  }).join("");

  fileTabs.querySelectorAll(".file-tab").forEach(btn => {
    btn.addEventListener("click", () => switchFile(btn.dataset.file));
  });
}

async function switchFile(filename) {
  if (currentFile === filename) return;
  await saveCurrentFile();
  currentFile = filename;
  docLabel.textContent = `${currentDoc.path} / ${currentFile}`;
  renderFileTabs();
  await loadFileContent(filename);
}

async function loadFileContent(filename) {
  if (!currentDoc) return;
  try {
    const resp = await fetch(`/api/docs/${currentDoc.path}?file=${filename}`);
    if (resp.ok) {
      const text = await resp.text();
      setEditorContent(text);
    }
  } catch (e) {
    console.warn("Could not load file:", filename, e);
  }
}

async function saveCurrentFile() {
  if (!currentDoc || !currentFile) return;
  const content = getEditorContent();
  try {
    if (currentDoc.path === "facts") {
      // The buffer holds a load-failure placeholder, not facts. Saving would
      // overwrite the real facts.yaml with it.
      if (factsLoadFailed) {
        showErrors([{ file: "facts.yaml", line: null, kind: "error",
          message: "facts.yaml never loaded — save blocked to avoid overwriting it." }]);
        return;
      }
      const resp = await fetch("/api/facts/raw", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ yaml_text: content }),
      });
      if (!resp.ok) {
        let msg = `HTTP ${resp.status}`;
        try { msg = (await resp.json()).detail || msg; } catch {}
        showErrors([{ file: "facts.yaml", line: null, kind: "error",
          message: `Facts not saved: ${msg}` }]);
      }
    } else {
      await fetch(`/api/docs/${currentDoc.path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content, file: currentFile }),
      });
    }
  } catch (e) {
    console.error("Save error:", e);
  }
}

// ── Compile ───────────────────────────────────────────────────────────────────

function scheduleCompile() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(triggerCompile, DEBOUNCE_MS);
}

async function triggerCompile() {
  if (!currentDoc) return;
  clearTimeout(debounceTimer);

  // Only auto-compile main.tex
  if (currentFile !== "main.tex") return;

  savedScrollTop  = pdfScroll.scrollTop;
  savedScrollLeft = pdfScroll.scrollLeft;
  setStatus("compiling");

  await saveCurrentFile();

  let result;
  try {
    const resp = await fetch("/api/compile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: currentDoc.path }),
    });
    result = await resp.json();
  } catch {
    setStatus("error");
    showErrors([{ file: "", line: null, message: "Compile request failed", kind: "error" }]);
    return;
  }

  showErrors([...result.errors, ...result.warnings]);

  if (result.success) {
    setStatus("ok");
    await loadPdf(result.pdf_url);
  } else {
    setStatus("error");
  }
}

// ── Status ────────────────────────────────────────────────────────────────────

function setStatus(state) {
  statusBadge.className = `badge ${state}`;
  statusBadge.textContent =
    state === "compiling" ? "Compiling…"
    : state === "ok"      ? "OK"
    : state === "error"   ? "Error"
    :                        "Idle";
}

// ── Error list ────────────────────────────────────────────────────────────────

function showErrors(items) {
  errorList.innerHTML = "";
  for (const e of items) {
    const div = document.createElement("div");
    div.className = `err-item kind-${e.kind}`;
    const tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = e.kind === "warning" ? "WARN" : "ERR";
    const loc = document.createElement("span");
    loc.className = "location";
    loc.textContent = e.line ? `L${e.line}` : "";
    const msg = document.createElement("span");
    msg.className = "msg";
    msg.textContent = e.message;
    div.append(tag, loc, msg);
    if (e.line) div.addEventListener("click", () => jumpToLine(e.line));
    errorList.appendChild(div);
  }
}

function jumpToLine(lineNumber) {
  if (!cmView) return;
  const total = cmView.state.doc.lines;
  const line  = cmView.state.doc.line(Math.min(lineNumber, total));
  cmView.dispatch({
    selection: { anchor: line.from },
    effects: EditorView.scrollIntoView(line.from, { y: "center" }),
  });
  cmView.focus();
}

// ── PDF ───────────────────────────────────────────────────────────────────────

async function tryLoadPdf() {
  if (!currentDoc) return;
  try {
    const head = await fetch(`/api/pdf/${currentDoc.path}`, { method: "HEAD" });
    if (head.ok) {
      await loadPdf(`/api/pdf/${currentDoc.path}`);
      setStatus("ok");
    }
  } catch (_) { /* no cached PDF */ }
}

async function loadPdf(url) {
  try {
    const arrayBuf = await fetch(`${url}?t=${Date.now()}`).then(r => r.arrayBuffer());
    const loadingTask = getDocument({ data: arrayBuf });
    pdfDoc = await loadingTask.promise;
    currentPage = 1;
    pdfPlaceholder.classList.add("hidden");
    await renderPage(currentPage);
    updatePageInfo();
    pdfScroll.scrollTop  = savedScrollTop;
    pdfScroll.scrollLeft = savedScrollLeft;
  } catch (e) {
    console.error("PDF load error:", e);
  }
}

async function renderPage(pageNum) {
  if (!pdfDoc) return;
  if (renderTask) { renderTask.cancel(); renderTask = null; }

  const page     = await pdfDoc.getPage(pageNum);
  const viewport = page.getViewport({ scale: zoomScale });
  const ctx      = pdfCanvas.getContext("2d");
  const dpr      = window.devicePixelRatio || 1;

  pdfCanvas.width        = viewport.width  * dpr;
  pdfCanvas.height       = viewport.height * dpr;
  pdfCanvas.style.width  = `${viewport.width}px`;
  pdfCanvas.style.height = `${viewport.height}px`;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  renderTask = page.render({ canvasContext: ctx, viewport });
  try {
    await renderTask.promise;
  } catch (e) {
    if (e?.name !== "RenderingCancelledException") console.error(e);
  }
  renderTask = null;
}

function updatePageInfo() {
  pageInfo.textContent     = pdfDoc ? `${currentPage} / ${pdfDoc.numPages}` : "– / –";
  $("btn-prev").disabled   = currentPage <= 1;
  $("btn-next").disabled   = !pdfDoc || currentPage >= pdfDoc.numPages;
}

// ── PDF controls ──────────────────────────────────────────────────────────────

$("btn-prev").addEventListener("click", async () => {
  if (!pdfDoc || currentPage <= 1) return;
  currentPage--;
  await renderPage(currentPage);
  updatePageInfo();
});
$("btn-next").addEventListener("click", async () => {
  if (!pdfDoc || currentPage >= pdfDoc.numPages) return;
  currentPage++;
  await renderPage(currentPage);
  updatePageInfo();
});
$("btn-zoom-in").addEventListener("click",  () => setZoom(zoomScale + 0.15));
$("btn-zoom-out").addEventListener("click", () => setZoom(zoomScale - 0.15));
$("btn-fit").addEventListener("click", fitWidth);
$("btn-compile").addEventListener("click", triggerCompile);

async function setZoom(scale) {
  zoomScale = Math.max(0.3, Math.min(4.0, scale));
  zoomLabel.textContent = `${Math.round(zoomScale * 100)}%`;
  if (pdfDoc) await renderPage(currentPage);
}

function fitWidth() {
  if (!pdfDoc) return;
  const containerW = pdfScroll.clientWidth - 32;
  pdfDoc.getPage(currentPage).then(page => {
    const vp = page.getViewport({ scale: 1 });
    setZoom(containerW / vp.width);
  });
}

// ── Sidebar toggle ────────────────────────────────────────────────────────────

$("btn-toggle-sidebar").addEventListener("click", () => {
  sidebarVisible = !sidebarVisible;
  sidebar.classList.toggle("collapsed", !sidebarVisible);
});

// ── Applications view toggle ──────────────────────────────────────────────────

$("btn-toggle-apps").addEventListener("click", toggleApplicationsView);
$("btn-close-apps").addEventListener("click", () => {
  appView.classList.add("hidden");
  $("app-layout").style.display = "";
});

function toggleApplicationsView() {
  if (appView.classList.contains("hidden")) {
    appView.classList.remove("hidden");
    $("app-layout").style.display = "none";
    loadApplications();
  } else {
    appView.classList.add("hidden");
    $("app-layout").style.display = "";
  }
}

async function loadApplications() {
  try {
    const resp = await fetch("/api/applications");
    const data = await resp.json();
    renderApplications(data.applications);
  } catch {
    appList.innerHTML = '<div class="app-empty">Could not load applications.</div>';
  }
}

function renderApplications(apps) {
  if (!apps.length) {
    appList.innerHTML = '<div class="app-empty">No applications yet.<br><small>Switch to Content mode and paste a job description to create your first one.</small></div>';
    $("applications-title").textContent = "Applications";
    return;
  }
  $("applications-title").textContent = `Applications (${apps.length})`;

  appList.innerHTML = apps.map((a, i) => {
    const total = a.matched_count + a.unmatched_count;
    const pct = total > 0 ? Math.round((a.matched_count / total) * 100) : 0;
    return `
    <div class="app-card">
      <div class="company">${a.company_name || "Unknown"}</div>
      <div class="role">${a.role_title || "Unknown role"}</div>
      <div class="meta">
        <span>📅 ${a.date_generated || ""}</span>
        <span class="score">✅ ${a.matched_count}/${total} matched (${pct}%)</span>
        ${a.unmatched_count > 0 ? `<span class="gaps-warn">⚠ ${a.unmatched_count} gaps</span>` : ""}
      </div>
      ${a.unmatched_list ? `<div class="meta" style="margin-top:4px"><span class="gaps-warn">⚠ ${a.unmatched_list}</span></div>` : ""}
      <div class="actions">
        ${a.letter_path ? `<button class="btn-open-letter" data-path="${a.letter_path}">📄 Letter</button>` : ""}
        ${a.cv_path ? `<button class="btn-open-cv" data-path="${a.cv_path}">⭐ CV</button>` : ""}
        <select class="status-select" data-index="${i}">
          <option value="generated" ${a.status === "generated" ? "selected" : ""}>generated</option>
          <option value="applied" ${a.status === "applied" ? "selected" : ""}>applied</option>
          <option value="interview" ${a.status === "interview" ? "selected" : ""}>interview</option>
          <option value="offer" ${a.status === "offer" ? "selected" : ""}>offer</option>
          <option value="rejected" ${a.status === "rejected" ? "selected" : ""}>rejected</option>
          <option value="withdrawn" ${a.status === "withdrawn" ? "selected" : ""}>withdrawn</option>
        </select>
      </div>
    </div>`;
  }).join("");

  // Wire open buttons
  appList.querySelectorAll(".btn-open-letter").forEach(btn => {
    btn.addEventListener("click", () => {
      appView.classList.add("hidden");
      $("app-layout").style.display = "";
      switchDocument(btn.dataset.path, "letter");
    });
  });
  appList.querySelectorAll(".btn-open-cv").forEach(btn => {
    btn.addEventListener("click", () => {
      appView.classList.add("hidden");
      $("app-layout").style.display = "";
      switchDocument(btn.dataset.path, "cv");
    });
  });

  // Wire status dropdowns
  appList.querySelectorAll(".status-select").forEach(sel => {
    sel.addEventListener("change", async () => {
      const index = parseInt(sel.dataset.index);
      const value = sel.value;
      await fetch(`/api/applications/${index}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ field: "status", value }),
      });
    });
  });
}

// ── Resize handle ─────────────────────────────────────────────────────────────

const handle = $("drag-handle");
handle.addEventListener("mousedown", (e) => {
  e.preventDefault();
  handle.classList.add("dragging");
  const onMove = (ev) => {
    const left  = workspaceEl.getBoundingClientRect().left;
    const pct   = Math.max(20, Math.min(80, ((ev.clientX - left) / workspaceEl.clientWidth) * 100));
    editorPane.style.width = `${pct}%`;
  };
  const onUp = () => {
    handle.classList.remove("dragging");
    document.removeEventListener("mousemove", onMove);
    document.removeEventListener("mouseup", onUp);
  };
  document.addEventListener("mousemove", onMove);
  document.addEventListener("mouseup", onUp);
});

// ── New document dropdown ─────────────────────────────────────────────────────

const btnNewDoc = $("btn-new-doc");
const newDocMenu = document.getElementById("new-doc-menu");

btnNewDoc.addEventListener("click", (e) => {
  e.stopPropagation();
  newDocMenu.classList.toggle("hidden");
});

document.addEventListener("click", (e) => {
  if (!btnNewDoc.contains(e.target) && !newDocMenu.contains(e.target)) {
    newDocMenu.classList.add("hidden");
  }
});

newDocMenu.querySelectorAll(".nd-item").forEach(item => {
  item.addEventListener("click", () => {
    newDocMenu.classList.add("hidden");
    const action = item.dataset.action;
    if (action === "letter") newFromTemplate("scrlttr2-letter", "letter");
    else if (action === "ats") newFromTemplate("ats-cv", "cv");
    else if (action === "designed") newFromTemplate("designed-cv", "cv");
    else if (action === "import") showImportCustomPanel();
  });
});

let modalMode = "create"; // "create" | "import" | "import-custom"

$("btn-import").addEventListener("click", async () => {
  modalMode = "import";
  openModal();
  showImportPanel();
});

function openModal() {
  modalOverlay.classList.remove("hidden");
  modalError.classList.add("hidden");
  modalCreate.disabled = true;
  modalCreate.classList.remove("hidden");
  newDocName.value = "";
  newDocName.style.display = "";
  templateGrid.classList.add("hidden");
  importPanel.classList.add("hidden");
  importCustomPanel.classList.add("hidden");
  modalImportBtn.classList.add("hidden");
  document.querySelector("#modal-footer label").style.display = "";
}

$("modal-close").addEventListener("click", () => { modalOverlay.classList.add("hidden"); });
modalOverlay.addEventListener("click", (e) => { if (e.target === modalOverlay) modalOverlay.classList.add("hidden"); });

function showImportPanel() {
  templateGrid.classList.add("hidden");
  modalCreate.classList.add("hidden");
  newDocName.style.display = "none";
  document.querySelector("#modal-footer label").style.display = "none";
  importPanel.classList.remove("hidden");
  modalImportBtn.classList.remove("hidden");
  importTextarea.value = "";
  modalImportBtn.disabled = false;
  modalImportBtn.textContent = "Import & Merge";
  document.querySelector("#modal-header span").textContent = "Import Work History";
}

function showImportCustomPanel() {
  modalMode = "import-custom";
  openModal();
  modalCreate.classList.add("hidden");
  importCustomPanel.classList.remove("hidden");
  importTex.value = "";
  importCls.value = "";
  importExtraFiles.innerHTML = "";
  importCustomStatus.innerHTML = "";
  newDocName.style.display = "";
  document.querySelector("#modal-footer label").style.display = "";
  modalCreate.classList.remove("hidden");
  modalCreate.disabled = false;
  modalCreate.textContent = "Create";
  document.querySelector("#modal-header span").textContent = "Import Custom CV";
}

// ── Import Custom CV — add extra file rows ─────────────────────────────────────
const importTex = $("import-tex");
const importCls = $("import-cls");
const importExtraFiles = $("import-extra-files");
const importCustomPanel = $("import-custom-panel");
const importCustomStatus = $("import-custom-status");
const btnAddExtraFile = $("btn-add-extra-file");

btnAddExtraFile.addEventListener("click", () => {
  const row = document.createElement("div");
  row.className = "import-extra-row";
  row.innerHTML = `
    <input type="text" class="import-extra-name" placeholder="filename (e.g. mystyle.sty)" style="flex:1;background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:4px 8px;color:var(--text);font-size:11px;font-family:'Cascadia Code',monospace">
    <button class="import-extra-rem" title="Remove">×</button>
    <textarea class="import-extra-content" placeholder="Paste file content..." style="width:100%;min-height:60px;resize:vertical;background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:8px;color:var(--text);font-size:11px;font-family:'Cascadia Code',monospace;line-height:1.4;margin-top:4px"></textarea>`;
  row.querySelector(".import-extra-rem").addEventListener("click", () => row.remove());
  importExtraFiles.appendChild(row);
});

// ── Modal: Create (import custom CV) ───────────────────────────────────────────
modalCreate.addEventListener("click", async () => {
  if (modalMode !== "import-custom") return;
  const name = newDocName.value.trim().replace(/\s+/g, "_").toLowerCase();
  if (!name) { modalError.textContent = "Enter a document name."; modalError.classList.remove("hidden"); return; }

  const texContent = importTex.value.trim();
  if (!texContent) { modalError.textContent = "Paste the .tex file content."; modalError.classList.remove("hidden"); return; }

  modalCreate.disabled = true;
  modalCreate.textContent = "Creating…";
  modalError.classList.add("hidden");

  const extraFiles = [];
  importExtraFiles.querySelectorAll(".import-extra-row").forEach(row => {
    const fn = row.querySelector(".import-extra-name").value.trim();
    const fc = row.querySelector(".import-extra-content").value.trim();
    if (fn && fc) extraFiles.push({ name: fn, content: fc });
  });

  try {
    const resp = await fetch("/api/docs/import-custom", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        tex_content: texContent,
        cls_content: importCls.value.trim(),
        cls_filename: "custom.cls",
        extra_files: extraFiles,
      }),
    });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || `HTTP ${resp.status}`);
    }
    const data = await resp.json();
    modalOverlay.classList.add("hidden");
    modalCreate.textContent = "Create";
    await loadDocList();
    await switchDocument(data.document.path, data.document.kind);
  } catch (e) {
    modalError.textContent = e.message || "Network error. Try again.";
    modalError.classList.remove("hidden");
    modalCreate.textContent = "Create";
    modalCreate.disabled = false;
  }
});

// ── Import & Merge ────────────────────────────────────────────────────────────

modalImportBtn.addEventListener("click", async () => {
  const text = importTextarea.value.trim();
  if (!text) return;

  modalImportBtn.disabled = true;
  modalImportBtn.textContent = "Importing…";

  try {
    const resp = await fetch("/api/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });

    if (!resp.ok) {
      modalError.textContent = "Import failed. Check format.";
      modalError.classList.remove("hidden");
      modalImportBtn.disabled = false;
      modalImportBtn.textContent = "Import & Merge";
      return;
    }

    const data = await resp.json();
    const count = data.roles_found || 0;

    await fetch("/api/facts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ facts: data.facts }),
    });

    modalOverlay.classList.add("hidden");
    modalImportBtn.textContent = "Import & Merge";

    if (currentDoc && currentDoc.path === "facts") {
      const factsResp = await fetch("/api/facts/raw");
      const factsText = await factsResp.text();
      setEditorContent(factsText);
    }

    modalError.classList.add("hidden");
    showErrors([{ file: "", line: null, message: `Imported ${count} roles. Facts saved. Review in Fact Bank.`, kind: "warning" }]);
  } catch (e) {
    modalError.textContent = "Network error. Try again.";
    modalError.classList.remove("hidden");
    modalImportBtn.disabled = false;
    modalImportBtn.textContent = "Import & Merge";
  }
});

// ── Chat: Provider/model switching ─────────────────────────────────────────────

chatProvider.addEventListener("change", loadChatModels);
loadChatModels();

async function loadChatModels() {
  const provider = chatProvider.value;
  chatModel.innerHTML = '<option value="">Auto (use provider default)</option>';
  try {
    const resp = await fetch(`/api/chat/models?provider=${provider}`);
    const data = await resp.json();
    _populateModelSelect(chatModel, data.models || []);
  } catch (_) {}
}

function _populateModelSelect($select, models) {
  const free = models.filter(m => m.free);
  const paid = models.filter(m => !m.free);
  let html = $select.innerHTML; // keep placeholder option
  if (free.length) {
    html += '<optgroup label="Free">';
    for (const m of free) {
      html += `<option value="${escapeHTML(m.id)}">${escapeHTML(m.name)} (free)</option>`;
    }
    html += '</optgroup>';
  }
  if (paid.length) {
    html += '<optgroup label="Paid">';
    for (const m of paid) {
      html += `<option value="${escapeHTML(m.id)}">${escapeHTML(m.name)}</option>`;
    }
    html += '</optgroup>';
  }
  if (!free.length && !paid.length) {
    for (const m of models) {
      const id = typeof m === "string" ? m : m.id;
      const name = typeof m === "string" ? m : m.name;
      html += `<option value="${escapeHTML(id)}">${escapeHTML(name)}</option>`;
    }
  }
  $select.innerHTML = html;
}

// ── Apply view: the job-search workflow ───────────────────────────────────────

function showView(which) {
  const apply = which === "apply";
  applyView.classList.toggle("hidden", !apply);
  appLayout.classList.toggle("hidden", apply);
  btnViewApply.classList.toggle("active", apply);
  btnViewEdit.classList.toggle("active", !apply);
  // Editor chrome is meaningless on the Apply screen
  document.querySelectorAll(".topbar-actions .editor-only")
    .forEach(el => el.classList.toggle("hidden", apply));
  if (!apply && cmView) cmView.requestMeasure();
}

btnViewApply.addEventListener("click", () => showView("apply"));
btnViewEdit.addEventListener("click", () => showView("edit"));

// ── Generic fetch + select helpers ──────────────────────────────────────────
async function fetchJSON(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}
function populateSelect($select, items, valueFn, labelFn, placeholder = null) {
  const val = $select.value;
  $select.innerHTML = placeholder ? `<option value="">${escapeHTML(placeholder)}</option>` : "";
  for (const item of items) {
    const v = valueFn(item);
    const l = labelFn(item);
    $select.innerHTML += `<option value="${escapeHTML(v)}">${escapeHTML(l)}</option>`;
  }
  // Restore selection if still valid
  if (val && [...$select.options].some(o => o.value === val)) $select.value = val;
}

applyProvider.addEventListener("change", loadApplyModels);

async function loadApplyModels() {
  applyModel.innerHTML = '<option value="">Auto</option>';
  try {
    const resp = await fetch(`/api/chat/models?provider=${applyProvider.value}`);
    const data = await resp.json();
    _populateModelSelect(applyModel, data.models || []);
  } catch (_) {}
}
loadApplyModels();

async function loadTemplates() {
  try {
    const data = await fetchJSON("/api/templates");
    const ALLOWED_CV = new Set(["ats-cv", "designed-cv"]);
    const cvs = (data.templates || []).filter(t => t.kind === "cv" && t.has_template && ALLOWED_CV.has(t.id));
    const letters = (data.templates || []).filter(t => t.kind === "letter" && t.has_template);
    populateSelect(optCvTemplate, cvs, t => t.id, t => t.name);
    if (letters.length > 0) {
      populateSelect(optLetterTemplate, letters, t => t.id, t => t.name);
      if (letters.length > 1) {
        const row = $("opt-letter-template-row");
        if (row) row.classList.remove("hidden");
      }
    }
  } catch (_) {}
}
async function loadLanguages() {
  try {
    const data = await fetchJSON("/api/i18n/languages");
    populateSelect(optLanguage, data.languages || [], l => l.code, l => `${l.native_name} (${l.english_name})`);
  } catch (_) {}
}
loadTemplates();
loadLanguages();

// ── API Key management ────────────────────────────────────────────────────────
const _APIKEY_PROVIDERS = [
  { id: "deepseek",   label: "DeepSeek",    placeholder: "sk-...",            link: "https://platform.deepseek.com",     pw: true },
  { id: "nvidia",     label: "NVIDIA",      placeholder: "nvapi-...",         link: "https://build.nvidia.com",          pw: true },
  { id: "openrouter", label: "OpenRouter",  placeholder: "sk-or-...",         link: "https://openrouter.ai/keys",        pw: true },
  { id: "ollama_url", label: "Ollama URL",  placeholder: "http://localhost:11434/v1", link: "", pw: false },
];

function _renderApiKeyPanel() {
  let html = "";
  for (const p of _APIKEY_PROVIDERS) {
    const linkHtml = p.link ? `<a href="${p.link}" target="_blank" class="apikey-link">get key ↗</a>` : "";
    html += `<div class="apikey-row" data-provider="${p.id}">
      <label>${p.label} ${linkHtml}</label>
      <input type="${p.pw ? 'password' : 'text'}" class="apikey-input" placeholder="${p.placeholder}" autocomplete="off">
      <button class="apikey-save btn-ghost">Save</button>
    </div>`;
  }
  const panelApply = $("api-key-panel-apply");
  const panelChat = $("api-key-panel-chat");
  if (panelApply) panelApply.innerHTML = html;
  if (panelChat) panelChat.innerHTML = html;

  // Wire save buttons in both panels
  document.querySelectorAll(".apikey-save").forEach(btn => {
    btn.addEventListener("click", async () => {
      const row = btn.closest(".apikey-row");
      const input = row.querySelector(".apikey-input");
      const provider = row.dataset.provider;
      const value = input.value.trim();
      btn.textContent = "…";
      try {
        const resp = await fetch("/api/settings/apikey", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ provider, value }),
        });
        if (!resp.ok) throw new Error((await resp.json()).detail || `HTTP ${resp.status}`);
        btn.classList.add("saved");
        btn.textContent = "Saved ✓";
        setTimeout(() => { btn.classList.remove("saved"); btn.textContent = "Save"; }, 2000);
      } catch (e) {
        btn.textContent = "Error";
        setTimeout(() => { btn.textContent = "Save"; }, 2000);
      }
    });
  });
}
_renderApiKeyPanel();

// ── Settings Modal ────────────────────────────────────────────────────────────
const settingsOverlay = $("settings-overlay");
const settingsProvider = $("settings-provider");
const settingsModel   = $("settings-model");
const settingsHint    = $("settings-provider-hint");

const PROVIDER_HINTS = {
  deepseek:   "Requires a DeepSeek API key. Fast & affordable.",
  nvidia:     "NVIDIA NIM offers free-tier models — get a free API key at build.nvidia.com.",
  openrouter: "OpenRouter aggregates many models. Free-tier models marked (free). Get a key at openrouter.ai.",
  ollama:     "Runs locally — no API key needed. Set the Ollama URL below.",
};

async function _loadSettingsModels() {
  if (!settingsProvider) return;
  settingsModel.innerHTML = '<option value="">Auto (provider default)</option>';
  try {
    const resp = await fetch(`/api/chat/models?provider=${settingsProvider.value}`);
    const data = await resp.json();
    _populateModelSelect(settingsModel, data.models || []);
  } catch (_) {}
  if (settingsHint) settingsHint.textContent = PROVIDER_HINTS[settingsProvider.value] || "";
}

function openSettingsModal() {
  // Sync modal selects with current apply/chat values
  if (settingsProvider && applyProvider) settingsProvider.value = applyProvider.value;
  _loadSettingsModels().then(() => {
    if (settingsModel && applyModel) {
      const cur = applyModel.value;
      if (cur && [...settingsModel.options].some(o => o.value === cur)) settingsModel.value = cur;
    }
  });
  _renderSettingsApiKeys();
  settingsOverlay.classList.remove("hidden");
  document.body.style.overflow = "hidden";
}

function closeSettingsModal() {
  settingsOverlay.classList.add("hidden");
  document.body.style.overflow = "";
}

function _renderSettingsApiKeys() {
  const panel = $("settings-apikey-panel");
  if (!panel) return;
  let html = "";
  for (const p of _APIKEY_PROVIDERS) {
    const linkHtml = p.link ? `<a href="${p.link}" target="_blank" class="apikey-link">get key ↗</a>` : "";
    html += `<div class="apikey-row" data-provider="${p.id}">
      <label class="settings-label">${p.label} ${linkHtml}</label>
      <input type="${p.pw ? 'password' : 'text'}" class="apikey-input" placeholder="${p.placeholder}" autocomplete="off">
      <button class="apikey-save btn-ghost">Save</button>
      <span class="apikey-status"></span>
    </div>`;
  }
  panel.innerHTML = html;
  panel.querySelectorAll(".apikey-save").forEach(btn => {
    btn.addEventListener("click", async () => {
      const row = btn.closest(".apikey-row");
      const input = row.querySelector(".apikey-input");
      const status = row.querySelector(".apikey-status");
      const provider = row.dataset.provider;
      const value = input.value.trim();
      if (!value) { status.textContent = "Enter a value first"; return; }
      btn.textContent = "…";
      try {
        const resp = await fetch("/api/settings/apikey", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ provider, value }),
        });
        if (!resp.ok) throw new Error((await resp.json()).detail || `HTTP ${resp.status}`);
        btn.textContent = "Save";
        status.textContent = "Saved ✓";
        status.style.color = "var(--accent)";
        setTimeout(() => { status.textContent = ""; }, 2500);
        input.value = "";
      } catch (e) {
        btn.textContent = "Save";
        status.textContent = "Error: " + e.message;
        status.style.color = "var(--error)";
      }
    });
  });
}

settingsProvider?.addEventListener("change", _loadSettingsModels);

$("settings-close")?.addEventListener("click", closeSettingsModal);
$("settings-cancel")?.addEventListener("click", closeSettingsModal);
settingsOverlay?.addEventListener("click", e => { if (e.target === settingsOverlay) closeSettingsModal(); });

$("settings-apply")?.addEventListener("click", () => {
  const prov = settingsProvider?.value;
  const mod  = settingsModel?.value;
  if (prov) {
    if (applyProvider) { applyProvider.value = prov; loadApplyModels().then(() => { if (mod && applyModel) applyModel.value = mod; }); }
    if (chatProvider)  { chatProvider.value  = prov; loadChatModels().then(() => { if (mod && chatModel) chatModel.value = mod; }); }
  }
  closeSettingsModal();
});

// Wire all ⚙ buttons to open settings modal
btnApplySettings?.addEventListener("click", openSettingsModal);
$("btn-settings")?.addEventListener("click", openSettingsModal);
$("btn-settings-chat")?.addEventListener("click", openSettingsModal);

// Clear cached translations when language changes so generate re-translates.
optLanguage.addEventListener("change", () => {
  if (tailorResultData) {
    tailorResultData = { ...tailorResultData, _translated_body: null, _translated_cv: null };
  }
});

btnApplyReset.addEventListener("click", resetApplyFlow);

function resetApplyFlow() {
  cancelPrefetch();
  if (analysisController) { analysisController.abort(); analysisController = null; }
  jdTextarea.value = "";
  tailorResultData = null;
  applyStatus.innerHTML = "";
  fitReport.innerHTML = "";
  generateStatus.innerHTML = "";
  applyDownloads.innerHTML = "";
  optLanguage.value = "en";
  [applyStep2, applyStep3, applyStep4].forEach(s => s.classList.add("hidden"));
  setProgressStep(1);
  jdTextarea.focus();
}

// ── Speculative pre-analysis ──────────────────────────────────────────────────
//
// The analysis is one long LLM round-trip, and the user spends a second or two
// after pasting before they reach for the button. Starting the same request on
// that pause hides most of the latency: by click time the answer is usually in
// hand, and Analyse just renders it.
//
// This spends tokens on work the user has not committed to, so it is kept on a
// short leash — one call per distinct ad, only after typing settles, and any
// superseded call is aborted rather than left to finish and bill.

const PREFETCH_DELAY_MS = 1200;
// Above the 120 the button enforces: speculation should wait for something that
// actually looks like a full posting rather than a half-finished paste.
const PREFETCH_MIN_CHARS = 300;

let prefetch = null;        // { jd, promise, controller, sink }
let prefetchTimer = null;
let analysisRunning    = false;
let analysisController = null;   // AbortController for direct (non-prefetch) analysis fetch

function setPrefetchHint(state) {
  if (!prefetchHint) return;
  prefetchHint.classList.toggle("ready", state === "ready");
  prefetchHint.textContent =
    state === "running" ? "preparing analysis…" :
    state === "ready"   ? "✓ analysis ready" : "";
}

function cancelPrefetch() {
  clearTimeout(prefetchTimer);
  if (prefetch) {
    try { prefetch.controller.abort(); } catch (_) {}
    prefetch = null;
  }
  setPrefetchHint("");
}

function startPrefetch(jd) {
  cancelPrefetch();
  const controller = new AbortController();
  // Progress messages from the stream go to a detached node — a speculative run
  // must not write over the status line the user is actually reading.
  const sink = document.createElement("div");

  const promise = (async () => {
    const resp = await fetch("/api/content/tailor", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job_ad_text: jd,
        provider: applyProvider.value || null,
        model: applyModel.value || null,
      }),
      signal: controller.signal,
    });
    if (!resp.ok) throw new Error((await resp.text()) || `HTTP ${resp.status}`);
    return await consumeTailorStream(resp, sink);
  })();

  const record = { jd, promise, controller, sink };
  prefetch = record;
  setPrefetchHint("running");

  promise.then(
    (data) => { if (prefetch === record) setPrefetchHint(data && data.success ? "ready" : ""); },
    ()     => { if (prefetch === record) setPrefetchHint(""); },
  );
}

function schedulePrefetch() {
  clearTimeout(prefetchTimer);
  if (analysisRunning) return;
  const jd = jdTextarea.value.trim();
  if (jd.length < PREFETCH_MIN_CHARS) { cancelPrefetch(); return; }
  if (prefetch && prefetch.jd === jd) return;   // already running or done for this ad
  cancelPrefetch();
  prefetchTimer = setTimeout(() => startPrefetch(jd), PREFETCH_DELAY_MS);
}

jdTextarea.addEventListener("input", schedulePrefetch);
// A cached result is answering the old question once the provider changes.
applyProvider.addEventListener("change", cancelPrefetch);
applyModel.addEventListener("change", cancelPrefetch);

btnAnalyse.addEventListener("click", analyseJob);

async function analyseJob() {
  const jd = jdTextarea.value.trim();
  if (!jd) {
    applyStatus.innerHTML = '<span class="apply-err">Paste a job description first.</span>';
    return;
  }
  if (jd.length < 120) {
    applyStatus.innerHTML = '<span class="apply-err">That looks too short to be a full job ad — paste the whole posting.</span>';
    return;
  }

  clearTimeout(prefetchTimer);
  analysisRunning = true;
  btnAnalyse.disabled = true;
  btnAnalyse.textContent = "Analysing…";
  applyStatus.innerHTML = '<span class="spinner"></span> Reading the job ad…';
  [applyStep2, applyStep3, applyStep4].forEach(s => s.classList.add("hidden"));

  try {
    let doneData = null;

    // Claim the speculative run when it was started for exactly this ad.
    if (prefetch && prefetch.jd === jd) {
      const claimed = prefetch;
      prefetch = null;
      setPrefetchHint("");
      try {
        doneData = await claimed.promise;
      } catch (_) {
        doneData = null;      // aborted or failed — fall through to a fresh run
      }
      // The stream reported a guard block or error into the detached sink.
      // Replay it instead of paying for an identical second call.
      if (!doneData && claimed.sink.innerHTML) {
        applyStatus.innerHTML = claimed.sink.innerHTML;
        return;
      }
    }

    if (!doneData) {
      cancelPrefetch();
      analysisController = new AbortController();
      const resp = await fetch("/api/content/tailor", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: analysisController.signal,
        body: JSON.stringify({
          job_ad_text: jd,
          provider: applyProvider.value || null,
          model: applyModel.value || null,
        }),
      });
      if (!resp.ok) {
        const msg = await resp.text();
        throw new Error(msg || `HTTP ${resp.status}`);
      }
      doneData = await consumeTailorStream(resp, applyStatus);
    }

    if (doneData && doneData.success) {
      tailorResultData = doneData;
      applyStatus.innerHTML = '<span class="apply-ok">✓ Analysed</span>';
      renderFitReport(doneData);
      applyStep2.classList.remove("hidden");
      applyStep3.classList.remove("hidden");
      setProgressStep(3);
      applyStep2.scrollIntoView({ behavior: "smooth", block: "start" });
    } else if (doneData) {
      applyStatus.innerHTML = `<span class="apply-err">${doneData.message || "Analysis failed"}</span>`;
    }
  } catch (e) {
    if (e.name === "AbortError") return;  // cancelled by user — resetApplyFlow handles UI
    applyStatus.innerHTML = `<span class="apply-err">${e.message || "Request failed"}</span>`;
  } finally {
    analysisRunning = false;
    analysisController = null;
    btnAnalyse.disabled = false;
    btnAnalyse.textContent = "Analyse Job";
  }
}

/** Read the tailor SSE stream. Returns the payload of the `done` event. */
async function consumeTailorStream(resp, statusEl) {
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let currentEvent = "message";
  let doneData = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line === "") { currentEvent = "message"; continue; }
      if (line.startsWith("event: ")) { currentEvent = line.slice(7).trim(); continue; }
      if (!line.startsWith("data: ")) continue;
      try {
        const data = JSON.parse(line.slice(6));

        if (currentEvent === "error") {
          statusEl.innerHTML = `<span class="apply-err">${data.error}</span>`;
          return null;
        }
        if (currentEvent === "status") {
          statusEl.innerHTML = `<span class="spinner"></span> ${data.message || ""}`;
        }
        if (currentEvent === "stage") {
          if (data.stage === "guard_failed") {
            statusEl.innerHTML =
              `<span class="apply-err"><b>Blocked by the fact guard.</b><br>` +
              data.errors.map(e => `Rule ${e.rule}: ${e.message}`).join("<br>") +
              `<br><small>Nothing was written. This is the guard doing its job — the model tried to state something that is not in your fact bank.</small></span>`;
            return null;
          }
          if (data.stage === "guard_warnings") {
            statusEl.innerHTML =
              `<span class="apply-warn">Warnings: ` +
              data.warnings.map(w => `R${w.rule} ${w.message}`).join("; ") + `</span>`;
          }
        }
        if (currentEvent === "done") { doneData = data; }
      } catch (_) {}
    }
  }
  return doneData;
}

function renderFitReport(d) {
  const score = d.fit_score ?? 0;
  const band = d.fit_band || "UNKNOWN";
  const bandClass = { STRONG: "fit-strong", STRETCH: "fit-stretch", SKIP: "fit-skip" }[band] || "fit-unknown";
  const bandIcon = { STRONG: "✅", STRETCH: "🟡", SKIP: "🔴" }[band] || "•";

  let html = `
    <div class="fit-headline ${bandClass}">
      <div class="fit-score">${score}<span class="pct">%</span></div>
      <div class="fit-verdict">
        <div class="fit-band">${bandIcon} ${band}</div>
        <div class="fit-reason">${escapeHTML(d.fit_reason || "")}</div>
      </div>
    </div>
    <div class="fit-job">
      <b>${escapeHTML(d.company_name || "")}</b> — ${escapeHTML(d.role_title || "")}
      ${d.location ? ` · ${escapeHTML(d.location)}` : ""}
    </div>`;

  const matched = d.matched || [];
  if (matched.length) {
    html += '<div class="fit-section-title">✅ What you match</div><div class="fit-rows">';
    for (const m of matched) {
      const pct = Math.round((m.confidence || 0) * 100);
      html += `<div class="result-row matched"><span class="phrase">${escapeHTML(m.phrase)}</span><span class="confidence">${pct}%</span></div>`;
    }
    html += "</div>";
  }

  const gaps = d.unmatched || [];
  const hard = new Set(d.hard_gaps || []);
  if (gaps.length) {
    html += '<div class="fit-section-title">⚠️ Gaps — be ready to address these</div><div class="fit-rows">';
    for (const g of gaps) {
      const isHard = hard.has(g);
      html += `<div class="result-row unmatched${isHard ? " hard" : ""}">
        <span class="phrase">${escapeHTML(g)}</span>
        ${isHard ? '<span class="hard-tag">hard requirement</span>' : ""}
      </div>`;
    }
    html += "</div>";
  }

  if (d.notes) {
    html += `<div class="fit-notes">💡 ${escapeHTML(d.notes)}</div>`;
  }

  // Add editable letter preview
  if (d.assembled_body) {
    html += `
      <div class="letter-preview-section" style="margin-top:16px;border-top:1px solid var(--border);padding-top:12px">
        <div class="fit-section-title">📝 Preview & Edit Letter Body</div>
        <textarea id="letter-preview-textarea" class="letter-preview-textarea">${escapeHTML(d.assembled_body)}</textarea>
        <div class="apply-actions" style="margin-top:10px">
          <button id="btn-reset-preview" class="btn-ghost">Reset to generated</button>
          <button id="btn-generate-from-preview" class="btn-primary" disabled style="opacity:0.5">Check & Generate →</button>
        </div>
        <div id="preview-guard-status" style="margin-top:8px;font-size:12px"></div>
      </div>`;
  }

  fitReport.innerHTML = html;

  // Wire preview buttons
  const previewTextarea = $("letter-preview-textarea");
  const btnResetPreview = $("btn-reset-preview");
  const btnGenerateFromPreview = $("btn-generate-from-preview");
  const previewGuardStatus = $("preview-guard-status");

  if (previewTextarea && d.assembled_body) {
    // Enable generate button immediately (guard check runs on click)
    btnGenerateFromPreview.disabled = false;
    btnGenerateFromPreview.style.opacity = "1";

    btnResetPreview.addEventListener("click", () => {
      previewTextarea.value = d.assembled_body;
      previewGuardStatus.innerHTML = "";
    });

    btnGenerateFromPreview.addEventListener("click", async () => {
      const editedText = previewTextarea.value.trim();
      btnGenerateFromPreview.disabled = true;
      btnGenerateFromPreview.textContent = "Checking...";
      previewGuardStatus.innerHTML = '<span class="spinner"></span> Checking against fact bank...';

      try {
        const resp = await fetch("/api/content/preview-check", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            assembled_text: editedText,
            job_ad_text: $("jd-textarea").value || "",
          }),
        });
        const checkResult = await resp.json();

        if (!checkResult.passed) {
          const errLines = checkResult.errors.map(e =>
            `<span style="color:var(--error)">R${e.rule}: ${e.message}</span>`
          ).join("<br>");
          previewGuardStatus.innerHTML = `<span class="apply-err">Blocked by the fact guard.<br>${errLines}</span>`;
          btnGenerateFromPreview.textContent = "Check & Generate →";
          btnGenerateFromPreview.disabled = false;
          return;
        }

        // Guard passed — proceed with generate using channel buttons
        // Store edited text in tailorResultData so generateDocs picks it up
        tailorResultData = { ...tailorResultData, edited_body: editedText };
        previewGuardStatus.innerHTML = '<span class="apply-ok">✓ Guard passed — select a channel below to generate</span>';
        btnGenerateFromPreview.textContent = "✓ Ready";
        applyStep3.scrollIntoView({ behavior: "smooth", block: "start" });
      } catch (e) {
        previewGuardStatus.innerHTML = `<span class="apply-err">Check failed: ${e.message}</span>`;
        btnGenerateFromPreview.textContent = "Check & Generate →";
        btnGenerateFromPreview.disabled = false;
      }
    });
  }
}

// ── Apply view: generate the documents ────────────────────────────────────────

// Single Generate button reads all form controls
btnGenerate.addEventListener("click", () => generateDocs());

async function generateDocs() {
  if (!tailorResultData) return;
  btnGenerate.disabled = true;
  btnGenerate.textContent = "Generating…";
  applyStep4.classList.add("hidden");

  const lang = optLanguage.value;

  // Auto-translate letter body when non-English is selected and translation hasn't run yet
  if (lang !== "en" && !tailorResultData._translated_body &&
      tailorResultData.assembled_body && docLetter.checked) {
    btnGenerate.textContent = "Translating…";
    generateStatus.innerHTML = '<span class="spinner"></span> Translating letter body to ' + lang + '…';
    // Include the English hook paragraph so the full letter body is translated together
    const hookText = tailorResultData.hook_text || "";
    const bodyText = tailorResultData.assembled_body || "";
    const textToTranslate = hookText ? hookText + "\n\n" + bodyText : bodyText;
    try {
      const tResp = await fetch("/api/content/translate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: textToTranslate,
          language: lang,
          provider: applyProvider.value || null,
          model: applyModel.value || null,
          job_ad_text: jdTextarea.value || "",
        }),
      });
      if (!tResp.ok) throw new Error(`Translation HTTP ${tResp.status}`);
      const tData = await tResp.json();
      if (tData.errors && tData.errors.length) {
        generateStatus.innerHTML = `<span class="apply-err">Translation blocked: ${tData.errors.map(e => e.message).join("; ")}</span>`;
        btnGenerate.disabled = false;
        btnGenerate.textContent = "Generate";
        return;
      }
      tailorResultData = { ...tailorResultData, _translated_body: tData.translated };
      generateStatus.innerHTML = '<span class="apply-ok">✓ Letter auto-translated</span>';
    } catch (e) {
      generateStatus.innerHTML = `<span class="apply-err">Auto-translation failed: ${e.message}</span>`;
      btnGenerate.disabled = false;
      btnGenerate.textContent = "Generate";
      return;
    }
    btnGenerate.textContent = "Generating…";
  }

  // Auto-translate CV content. Separate call from the letter: the CV is a map of
  // short fields, not one prose blob, so it round-trips as keyed JSON.
  if (lang !== "en" && !tailorResultData._translated_cv && docCv.checked) {
    btnGenerate.textContent = "Translating CV…";
    generateStatus.innerHTML = '<span class="spinner"></span> Translating CV content to ' + lang + '…';
    try {
      const cvResp = await fetch("/api/content/translate-cv", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          language: lang,
          selected_bullet_ids: tailorResultData.selected_bullet_ids || [],
          optimized_bullets: tailorResultData.optimized_bullets || [],
          job_ad_text: jdTextarea.value || "",
          matched_phrases: (tailorResultData.matched || []).map(m => m.phrase || m.jd_phrase || "").filter(Boolean),
          provider: applyProvider.value || null,
          model: applyModel.value || null,
        }),
      });
      if (!cvResp.ok) throw new Error(`CV translation HTTP ${cvResp.status}`);
      const cvData = await cvResp.json();
      if (cvData.errors && cvData.errors.length) {
        generateStatus.innerHTML = `<span class="apply-err">CV translation blocked: ${cvData.errors.map(e => e.message).join("; ")}</span>`;
        btnGenerate.disabled = false;
        btnGenerate.textContent = "Generate";
        return;
      }
      const cvTranslated = cvData.translated;
      if (!cvTranslated || Object.keys(cvTranslated).length === 0) {
        generateStatus.innerHTML = '<span class="apply-err">CV translation returned empty — check provider or retry.</span>';
        btnGenerate.disabled = false;
        btnGenerate.textContent = "Generate";
        return;
      }
      tailorResultData = { ...tailorResultData, _translated_cv: cvTranslated };
      const n = Object.keys(cvTranslated).length;
      generateStatus.innerHTML = `<span class="apply-ok">✓ CV auto-translated (${n} fields)</span>`;
    } catch (e) {
      generateStatus.innerHTML = `<span class="apply-err">CV translation failed: ${e.message}</span>`;
      btnGenerate.disabled = false;
      btnGenerate.textContent = "Generate";
      return;
    }
    btnGenerate.textContent = "Generating…";
  }

  generateStatus.innerHTML = '<span class="spinner"></span> Building documents, then compiling…';

  const d = tailorResultData;
  const wantLetter = docLetter.checked;
  const wantCv = docCv.checked;
  const documents = [];
  if (wantLetter) documents.push("letter");
  if (wantCv) documents.push("cv");

  if (documents.length === 0) {
    generateStatus.innerHTML = '<span class="apply-err">Select at least one document to generate.</span>';
    btnGenerate.disabled = false;
    btnGenerate.textContent = "Generate";
    return;
  }

  try {
    const resp = await fetch("/api/content/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        channel: "portal",
        documents,
        language: optLanguage.value,
        cv_template: optCvTemplate.value || "",
        letter_template: optLetterTemplate.value || "",
        company_name: d.company_name || "",
        role_title: d.role_title || "",
        location: d.location || "",
        focus_phrase: d.focus_phrase || "",
        hook_key: d.hook_key || "",
        selected_bullet_ids: d.selected_bullet_ids || [],
        optimized_bullets: d.optimized_bullets || [],
        unmatched: d.unmatched || [],
        matched_count: (d.matched || []).length,
        notes: d.notes || "",
        edited_body: d._translated_body || d.edited_body || null,
        job_ad_text: $("jd-textarea").value || "",
        matched_phrases: (d.matched || []).map(m => m.jd_phrase || "").filter(Boolean),
        translated_cv: d._translated_cv || {},
      }),
    });

    if (!resp.ok) {
      const msg = await resp.text();
      throw new Error(msg || `HTTP ${resp.status}`);
    }
    const out = await resp.json();
    generateStatus.innerHTML = `<span class="apply-ok">✓ Generated — ${out.cv_variant}</span>`;
    renderDownloads(out);
    applyStep4.classList.remove("hidden");
    setProgressStep(4);
    applyStep4.scrollIntoView({ behavior: "smooth", block: "start" });
    loadDocList();
  } catch (e) {
    generateStatus.innerHTML = `<span class="apply-err">${e.message || "Generation failed"}</span>`;
  } finally {
    btnGenerate.disabled = false;
    btnGenerate.textContent = "Generate";
  }
}

function renderDownloads(out) {
  const row = (item, label) => {
    if (!item) return "";
    const ok = item.success;
    const status = ok
      ? '<span class="dl-meta">compiled ✓</span>'
      : `<span class="dl-meta" style="color:var(--error)">compile failed — open to fix</span>`;
    const link = ok
      ? `<a href="${item.url}" download="${item.filename}">⬇ ${escapeHTML(item.filename)}</a>`
      : `<span>${escapeHTML(item.filename)}</span>`;
    return `<div class="dl-row">
      <span>${label}</span>
      ${link}
      ${status}
      <button class="dl-open" data-path="${escapeHTML(item.doc_path)}">Open in editor</button>
    </div>`;
  };

  const items = (out.documents || ["letter", "cv"])
    .map(k => ({ key: k, label: k === "letter" ? "✉️ Letter" : "📄 CV", item: out[k] }))
    .filter(x => x.item)
    .map(x => row(x.item, x.label))
    .join("");

  applyDownloads.innerHTML = items +
    (out.language && out.language !== "en"
      ? `<div class="fit-notes">Generated in <b>${escapeHTML(out.language)}</b>.</div>`
      : `<div class="fit-notes">Logged to Applications (📊 in the top bar). ` +
        `CV variant: <b>${escapeHTML(out.cv_variant)}</b>.</div>`);

  applyDownloads.querySelectorAll(".dl-open").forEach(btn => {
    btn.addEventListener("click", async () => {
      const path = btn.dataset.path;
      showView("edit");
      await loadDocList();
      await switchDocument(path, path.startsWith("letters/") ? "letter" : "cv");
    });
  });
}

// ── Progress bar ──────────────────────────────────────────────────────────────
function setProgressStep(n) {
  document.querySelectorAll(".ap-node").forEach(el => {
    el.classList.toggle("active", +el.dataset.step <= n);
  });
  const pct = Math.max(0, (n - 1) / 3 * 100);
  const fill = document.getElementById("ap-fill");
  if (fill) fill.style.width = pct + "%";
}

// ── Panel tabs (AI Help | Files) ──────────────────────────────────────────────
document.querySelectorAll(".panel-tab").forEach(tab => {
  tab.addEventListener("click", () => switchPanel(tab.dataset.panel));
});

function switchPanel(panel) {
  document.querySelectorAll(".panel-tab").forEach(t => t.classList.toggle("active", t.dataset.panel === panel));
  const controls = document.getElementById("chat-controls");
  const msgs = document.getElementById("chat-messages");
  const inputRow = document.getElementById("chat-input-row");
  const fm = document.getElementById("file-manager-panel");
  const isAI = panel === "ai";
  if (controls) controls.classList.toggle("hidden", !isAI);
  if (msgs) msgs.classList.toggle("hidden", !isAI);
  if (inputRow) inputRow.classList.toggle("hidden", !isAI);
  if (fm) fm.classList.toggle("hidden", isAI);
  if (!isAI) loadFileManager();
}

// ── File manager ──────────────────────────────────────────────────────────────
async function loadFileManager() {
  if (!currentDoc) return;
  const fmList = document.getElementById("fm-file-list");
  if (!fmList) return;
  fmList.innerHTML = '<span class="spinner"></span> Loading…';
  try {
    const resp = await fetch(`/api/docs/${currentDoc.path}/files`);
    const data = await resp.json();
    const files = (data.files || []).filter(f => {
      const name = typeof f === "string" ? f : f.name;
      return name !== "document.json";
    });
    const fmRows = files.map(f => {
      const name = typeof f === "string" ? f : f.name;
      const size = typeof f === "string" ? null : (f.size || 0);
      const ext = name.split(".").pop().toLowerCase();
      const icons = { tex: "📝", sty: "⚙️", cls: "⚙️", yaml: "📋", png: "🖼️", jpg: "🖼️", jpeg: "🖼️", gif: "🖼️", pdf: "📄", eps: "📐", svg: "🎨" };
      const icon = icons[ext] || "📦";
      let sizeStr = "";
      if (size !== null) {
        if (size < 1024) sizeStr = "< 1 KB";
        else if (size < 1048576) sizeStr = Math.round(size / 1024) + " KB";
        else sizeStr = (size / 1048576).toFixed(1) + " MB";
      }
      return `<div class="fm-row">
        <span class="fm-icon">${icon}</span>
        <span class="fm-name">${escapeHTML(name)}</span>
        ${sizeStr ? `<span class="fm-size">${sizeStr}</span>` : ""}
        <button class="fm-delete" data-fm-file="${escapeHTML(name)}" title="Delete">×</button>
      </div>`;
    }).join("");
    fmList.innerHTML = fmRows || '<div style="padding:8px 10px;color:var(--text-dim);font-size:11px">No files</div>';

    fmList.querySelectorAll(".fm-delete").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        deleteWorkspaceFile(btn.dataset.fmFile, btn);
      });
    });
  } catch (_) {
    fmList.innerHTML = '<div style="padding:8px 10px;color:var(--text-dim);font-size:11px">Could not load files</div>';
  }
}

async function deleteWorkspaceFile(filename, btn) {
  if (!currentDoc) return;
  if (!confirm(`Delete "${filename}" from workspace?`)) return;
  btn.disabled = true;
  const fmStatus = document.getElementById("fm-status");
  try {
    const resp = await fetch(`/api/docs/${currentDoc.path}/file/${filename}`, { method: "DELETE" });
    if (!resp.ok) throw new Error((await resp.json()).detail || `HTTP ${resp.status}`);
    if (fmStatus) fmStatus.innerHTML = '<span style="color:var(--ok)">Deleted</span>';
    loadFileManager();
  } catch (e) {
    if (fmStatus) fmStatus.innerHTML = `<span style="color:var(--error)">${e.message}</span>`;
    btn.disabled = false;
  }
}

document.getElementById("fm-upload-input")?.addEventListener("change", async (e) => {
  if (!currentDoc) return;
  const file = e.target.files[0];
  if (!file) return;
  const fmStatus = document.getElementById("fm-status");
  const form = new FormData();
  form.append("file", file);
  try {
    const resp = await fetch(`/api/docs/${currentDoc.path}/upload`, { method: "POST", body: form });
    if (!resp.ok) throw new Error((await resp.json()).detail || `HTTP ${resp.status}`);
    if (fmStatus) fmStatus.innerHTML = `<span style="color:var(--ok)">Uploaded ${escapeHTML(file.name)}</span>`;
    loadFileManager();
  } catch (err) {
    if (fmStatus) fmStatus.innerHTML = `<span style="color:var(--error)">${err.message}</span>`;
  }
  e.target.value = "";
});

document.getElementById("fm-import-template")?.addEventListener("click", () => { showImportCustomPanel(); });

// ── Sidebar resize handle ─────────────────────────────────────────────────────
(function initSidebarResize() {
  const sidebar = document.getElementById("sidebar");
  const handle = document.getElementById("sidebar-resize-handle");
  if (!sidebar || !handle) return;

  let dragging = false;
  let startX = 0;
  let startW = 0;

  handle.addEventListener("mousedown", (e) => {
    dragging = true;
    startX = e.clientX;
    startW = sidebar.offsetWidth;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    e.preventDefault();
  });

  document.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const w = Math.max(160, Math.min(360, startW + (e.clientX - startX)));
    sidebar.style.width = w + "px";
    sidebar.style.minWidth = w + "px";
    document.documentElement.style.setProperty("--sidebar-w", w + "px");
  });

  document.addEventListener("mouseup", () => {
    if (!dragging) return;
    dragging = false;
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
    const w = sidebar.offsetWidth;
    localStorage.setItem("sidebar-width", w);
  });
})();


// ── Chat: Send message ─────────────────────────────────────────────────────────

btnChatSend.addEventListener("click", sendChatMessage);
chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendChatMessage();
  }
});

async function sendChatMessage() {
  if (isStreaming) return stopStreaming();
  const text = chatInput.value.trim();
  if (!text) return;

  if (!currentDoc) return;

  chatInput.value = "";
  chatInput.style.height = "auto";
  chatHistory.push({ role: "user", content: text });
  clearChatEmpty();
  appendChatBubble("user", text);

  const assistantBubble = appendChatBubble("assistant", "", true);
  const statusLine = document.createElement("div");
  statusLine.className = "chat-status-line";
  statusLine.textContent = "Asking LLM...";
  assistantBubble.appendChild(statusLine);

  chatAbortController = new AbortController();
  isStreaming = true;
  btnChatSend.textContent = "Stop";
  btnChatSend.style.background = "var(--error)";

  let fullText = "";
  let patchedText = "";
  let finalDiff = "";
  let finalWarnings = [];
  let success = false;
  let iterations = 0;
  let currentStep = "";

  try {
    const resp = await fetch("/api/chat/apply-and-fix", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        doc_path: currentDoc.path,
        file: currentFile,
        prompt: text,
        provider: chatProvider.value || null,
        model: chatModel.value || null,
      }),
      signal: chatAbortController.signal,
    });

    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`);
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let currentEvent = "message";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (line.startsWith("event: ")) {
          currentEvent = line.slice(7).trim();
          continue;
        }

        if (line.startsWith("data: ")) {
          try {
            const data = JSON.parse(line.slice(6));

            if (currentEvent === "error") {
              statusLine.textContent = `Error: ${data.error}`;
              statusLine.style.color = "var(--error)";
              return;
            }

            if (currentEvent === "status") {
              currentStep = data.step;
              statusLine.textContent = data.message || "";
              if (data.step === "compiling") {
                statusLine.innerHTML = `<span class="spinner"></span> ${data.message}`;
              }
              chatMessages.scrollTop = chatMessages.scrollHeight;
              continue;
            }

            if (currentEvent === "compile") {
              const errors = data.errors || [];
              if (errors.length > 0) {
                const errList = errors.map(e => `L${e.line || "?"}: ${e.message}`).join("<br>");
                statusLine.innerHTML = `<span style="color:var(--error);font-size:11px">✗ Compile errors (attempt ${data.iteration}):<br>${errList}</span>`;
              } else {
                statusLine.innerHTML = `<span style="color:var(--ok)">✓ Compiled clean</span>`;
              }
              chatMessages.scrollTop = chatMessages.scrollHeight;
              continue;
            }

            if (currentEvent === "done") {
              success = data.success;
              iterations = data.iterations;
              patchedText = data.patched || "";
              finalDiff = data.diff || "";
              finalWarnings = data.warnings || [];
              if (data.reply) {
                // Conversational response — no code patch
                chatHistory.push({ role: "assistant", content: data.reply });
                assistantBubble.textContent = data.reply;
                statusLine.remove();
              }
              break;
            }

            if (data.token) {
              fullText += data.token;
              statusLine.textContent = fullText;
              chatMessages.scrollTop = chatMessages.scrollHeight;
            }
          } catch (_) {}
        }
      }
    }

    if (success) {
      chatHistory.push({ role: "assistant", content: fullText });
      assistantBubble.textContent = "";
      assistantBubble.appendChild(statusLine);
      statusLine.innerHTML = `<span style="color:var(--ok)">✓ Done${iterations > 1 ? ` (fixed in ${iterations} attempts)` : ""}</span>`;
      setEditorContent(patchedText);
      triggerCompile();
      if (finalWarnings.length > 0) {
        showErrors(finalWarnings);
      }
    } else if (patchedText) {
      statusLine.innerHTML = `<span style="color:var(--error)">✗ Could not fix after ${iterations} attempts. Last attempt applied.</span>`;
      setEditorContent(patchedText);
      triggerCompile();
    } else {
      statusLine.textContent = "Error: No response from LLM.";
      statusLine.style.color = "var(--error)";
    }
  } catch (e) {
    if (e.name !== "AbortError") {
      statusLine.textContent = `Error: ${e.message || "Request failed"}`;
      statusLine.style.color = "var(--error)";
    } else {
      statusLine.textContent = "[Cancelled]";
    }
  } finally {
    isStreaming = false;
    chatAbortController = null;
    btnChatSend.textContent = "Send";
    btnChatSend.style.background = "";
    assistantBubble.classList.remove("streaming");
    chatInput.focus();
  }
}

function stopStreaming() {
  if (chatAbortController) {
    chatAbortController.abort();
    chatAbortController = null;
  }
}

// ── Chat: Content mode — JD tailoring ──────────────────────────────────────────


function clearChatEmpty() {
  const empty = chatMessages.querySelector(".chat-empty");
  if (empty) empty.remove();
}

btnChatClear.addEventListener("click", () => {
  chatHistory = [];
  tailorResults.classList.add("hidden");
  tailorResults.innerHTML = "";
  chatMessages.innerHTML = '<div class="chat-empty">Ask the AI to edit your LaTeX code.<br><small>e.g. "make section headers blue", "increase font size to 12pt"</small></div>';
});

function appendChatBubble(role, content, isStreamingBubble) {
  const div = document.createElement("div");
  div.className = `chat-msg ${role}`;
  if (isStreamingBubble) div.classList.add("streaming");
  div.textContent = content;
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return div;
}

function escapeHTML(str) {
  const div = document.createElement("div");
  div.textContent = str || "";
  return div.innerHTML;
}

// ── Chat: Auto-resize input ────────────────────────────────────────────────────

chatInput.addEventListener("input", () => {
  chatInput.style.height = "auto";
  chatInput.style.height = Math.min(chatInput.scrollHeight, 80) + "px";
});

// ── Chat: Drag handle (resize chat panel) ──────────────────────────────────────

chatResizeHandle.addEventListener("mousedown", (e) => {
  e.preventDefault();
  const startY = e.clientY;
  const startHeight = chatPanel.offsetHeight;

  const onMove = (ev) => {
    const delta = startY - ev.clientY;
    const newH = Math.max(40, Math.min(500, startHeight + delta));
    chatPanel.style.height = newH + "px";
  };

  const onUp = () => {
    document.removeEventListener("mousemove", onMove);
    document.removeEventListener("mouseup", onUp);
  };

  document.addEventListener("mousemove", onMove);
  document.addEventListener("mouseup", onUp);
});

// ── Profiles ──────────────────────────────────────────────────────────────────

const profileSelect  = $("profile-select");
const btnNewProfile  = $("btn-new-profile");

async function loadProfiles() {
  try {
    const resp = await fetch("/api/profiles");
    const data = await resp.json();
    const profiles = data.profiles || [];
    profileSelect.innerHTML = profiles.map(p =>
      `<option value="${p.id}" ${p.id === data.active ? "selected" : ""}>${p.name}</option>`
    ).join("");
    if (!profiles.length) {
      profileSelect.innerHTML = '<option value="">Default</option>';
    }
  } catch (e) {
    console.warn("Could not load profiles:", e);
  }
}

profileSelect.addEventListener("change", async () => {
  const id = profileSelect.value;
  if (!id) return;
  try {
    await fetch("/api/profiles/switch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    await loadDocList();
    if (currentDoc) {
      await switchDocument(currentDoc.path, currentDoc.kind);
    } else {
      try {
        const resp = await fetch("/api/docs");
        const data = await resp.json();
        const docs = data.documents;
        const cvDoc = docs.find(d => d.path === "cv");
        if (cvDoc) await switchDocument("cv", "cv");
      } catch (_) {}
    }
  } catch (e) {
    console.error("Profile switch failed:", e);
  }
});

btnNewProfile.addEventListener("click", async () => {
  const name = prompt("New profile name (e.g. 'Aerospace CV'):");
  if (!name || !name.trim()) return;
  try {
    const resp = await fetch("/api/profiles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name.trim() }),
    });
    if (!resp.ok) {
      const err = await resp.text();
      alert("Could not create profile: " + err);
      return;
    }
    const data = await resp.json();
    await fetch("/api/profiles/switch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: data.profile.id }),
    });
    await loadProfiles();
    await loadDocList();
    setStatus("idle");
  } catch (e) {
    console.error("Profile creation failed:", e);
  }
});

(async function init() {
  await loadProfiles();
  await loadDocList();
  try {
    const resp = await fetch("/api/docs");
    const data = await resp.json();
    const docs = data.documents;
    const cvDoc = docs.find(d => d.path === "cv");
    if (cvDoc) {
      await switchDocument("cv", "cv");
    } else if (docs.length > 0) {
      await switchDocument(docs[0].path, docs[0].kind);
    }
  } catch (_) {}
})();
