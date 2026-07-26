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
const btnApplyReset  = $("btn-apply-reset");
const applyStatus    = $("apply-status");
const fitReport      = $("fit-report");
const generateStatus = $("generate-status");
const applyDownloads = $("apply-downloads");
const applyStep2     = $("apply-step-2");
const applyStep3     = $("apply-step-3");
const applyStep4     = $("apply-step-4");

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

function renderDocList(docs) {
  let html = docs.map(d => {
    const icon = d.kind === "letter" ? "✉️" : "📄";
    const active = currentDoc && currentDoc.path === d.path ? " active" : "";
    return `<div class="doc-item${active}" data-path="${d.path}" data-kind="${d.kind}">
      <span class="doc-icon">${icon}</span>
      <span class="doc-name">${d.name}</span>
    </div>`;
  }).join("");

  // Add Fact Bank entry
  const factsActive = currentDoc && currentDoc.path === "facts" ? " active" : "";
  html += `<div class="doc-item${factsActive}" data-path="facts" data-kind="facts" style="margin-top:4px;border-top:1px solid var(--border);padding-top:8px;">
    <span class="doc-icon">📋</span>
    <span class="doc-name">Fact Bank</span>
  </div>`;

  if (!docs.length) {
    docList.innerHTML = html || '<div class="sidebar-empty">No documents yet. Click <strong>+ New</strong> to create one.</div>';
  } else {
    docList.innerHTML = html;
  }

  // Click handlers
  docList.querySelectorAll(".doc-item").forEach(el => {
    el.addEventListener("click", () => switchDocument(el.dataset.path, el.dataset.kind));
  });
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
      const text = await resp.text();
      setEditorContent(text);
    } catch (e) {
      setEditorContent("# Could not load facts.yaml");
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

  // Load file list
  try {
    const resp = await fetch(`/api/docs/${path}/files`);
    const data = await resp.json();
    docFiles = data.files || [];
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
      await fetch("/api/facts/raw", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ yaml_text: content }),
      });
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

// ── Modal: Template picker & new document ─────────────────────────────────────

let modalMode = "create"; // "create" | "import"

$("btn-new-doc").addEventListener("click", async () => {
  modalMode = "create";
  openModal();
  await loadTemplateGrid();
});

$("btn-import").addEventListener("click", async () => {
  modalMode = "import";
  openModal();
  showImportPanel();
});

function openModal() {
  modalOverlay.classList.remove("hidden");
  modalError.classList.add("hidden");
  modalCreate.disabled = true;
  newDocName.value = "";
  templateGrid.classList.remove("hidden");
  importPanel.classList.add("hidden");
  modalImportBtn.classList.add("hidden");
  modalCreate.classList.remove("hidden");
  newDocName.style.display = "";
  document.querySelector("#modal-footer label").style.display = "";
  document.querySelector("#modal-header span").textContent = modalMode === "import" ? "Import Work History" : "New Document — Choose Template";
}

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
}

async function loadTemplateGrid() {
  try {
    const resp = await fetch("/api/templates");
    const data = await resp.json();
    renderTemplateGrid(data.templates);
  } catch {
    templateGrid.innerHTML = '<p style="color:var(--error);padding:16px">Could not load templates.</p>';
  }
}

$("modal-close").addEventListener("click", () => {
  modalOverlay.classList.add("hidden");
});

modalOverlay.addEventListener("click", (e) => {
  if (e.target === modalOverlay) modalOverlay.classList.add("hidden");
});

function renderTemplateGrid(templates) {
  if (!templates.length) {
    templateGrid.innerHTML = '<p class="grid-empty">No templates available.</p>';
    return;
  }
  templateGrid.innerHTML = templates.map(t => `
    <div class="tpl-card" data-id="${t.id}" data-kind="${t.kind}">
      <div class="tpl-icon" style="background:${t.colour || 'var(--accent)'}">${t.icon || '📄'}</div>
      <div class="tpl-name">${t.name}</div>
      <div class="tpl-desc">${t.description}</div>
      <div class="tpl-kind">${t.kind === 'letter' ? 'Cover Letter' : 'CV'}</div>
    </div>
  `).join("");

  let selectedTemplate = null;
  templateGrid.querySelectorAll(".tpl-card").forEach(card => {
    card.addEventListener("click", () => {
      templateGrid.querySelectorAll(".tpl-card").forEach(c => c.classList.remove("selected"));
      card.classList.add("selected");
      selectedTemplate = card.dataset.id;
      modalCreate.disabled = !newDocName.value.trim();
    });
  });

  newDocName.oninput = () => {
    modalCreate.disabled = !selectedTemplate || !newDocName.value.trim();
    modalError.classList.add("hidden");
  };
}

modalCreate.addEventListener("click", async () => {
  const selected = templateGrid.querySelector(".tpl-card.selected");
  if (!selected) return;

  const templateId = selected.dataset.id;
  const name = newDocName.value.trim().replace(/\s+/g, "_").toLowerCase();
  if (!name) return;

  modalCreate.disabled = true;
  modalCreate.textContent = "Creating…";

  try {
    const resp = await fetch(`/api/templates/${templateId}/create`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ template_id: templateId, name }),
    });

    if (!resp.ok) {
      const err = await resp.text();
      modalError.textContent = err;
      modalError.classList.remove("hidden");
      modalCreate.textContent = "Create";
      modalCreate.disabled = false;
      return;
    }

    const data = await resp.json();
    const doc = data.document;
    modalOverlay.classList.add("hidden");
    modalCreate.textContent = "Create";
    await loadDocList();
    await switchDocument(doc.path, doc.kind);
  } catch (e) {
    modalError.textContent = "Network error. Try again.";
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
    for (const m of data.models || []) {
      chatModel.innerHTML += `<option value="${m.id}">${m.name}</option>`;
    }
  } catch (_) {}
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

applyProvider.addEventListener("change", loadApplyModels);

async function loadApplyModels() {
  applyModel.innerHTML = '<option value="">Auto</option>';
  try {
    const resp = await fetch(`/api/chat/models?provider=${applyProvider.value}`);
    const data = await resp.json();
    for (const m of data.models || []) {
      applyModel.innerHTML += `<option value="${m.id}">${m.name}</option>`;
    }
  } catch (_) {}
}
loadApplyModels();

btnApplyReset.addEventListener("click", resetApplyFlow);

function resetApplyFlow() {
  jdTextarea.value = "";
  tailorResultData = null;
  applyStatus.innerHTML = "";
  fitReport.innerHTML = "";
  generateStatus.innerHTML = "";
  applyDownloads.innerHTML = "";
  [applyStep2, applyStep3, applyStep4].forEach(s => s.classList.add("hidden"));
  jdTextarea.focus();
}

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

  btnAnalyse.disabled = true;
  btnAnalyse.textContent = "Analysing…";
  applyStatus.innerHTML = '<span class="spinner"></span> Reading the job ad…';
  [applyStep2, applyStep3, applyStep4].forEach(s => s.classList.add("hidden"));

  try {
    const resp = await fetch("/api/content/tailor", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job_ad_text: jd,
        provider: applyProvider.value || null,
        model: applyModel.value || null,
      }),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

    const doneData = await consumeTailorStream(resp, applyStatus);

    if (doneData && doneData.success) {
      tailorResultData = doneData;
      applyStatus.innerHTML = '<span class="apply-ok">✓ Analysed</span>';
      renderFitReport(doneData);
      applyStep2.classList.remove("hidden");
      applyStep3.classList.remove("hidden");
      applyStep2.scrollIntoView({ behavior: "smooth", block: "start" });
    } else if (doneData) {
      applyStatus.innerHTML = `<span class="apply-err">${doneData.message || "Analysis failed"}</span>`;
    }
  } catch (e) {
    applyStatus.innerHTML = `<span class="apply-err">${e.message || "Request failed"}</span>`;
  } finally {
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

  fitReport.innerHTML = html;
}

// ── Apply view: generate the documents ────────────────────────────────────────

$("btn-channel-portal").addEventListener("click", () => generateDocs("portal"));
$("btn-channel-email").addEventListener("click", () => generateDocs("email"));

async function generateDocs(channel) {
  if (!tailorResultData) return;
  const buttons = document.querySelectorAll(".channel-btn");
  buttons.forEach(b => b.disabled = true);
  generateStatus.innerHTML = '<span class="spinner"></span> Building your CV and cover letter, then compiling both…';
  applyStep4.classList.add("hidden");

  const d = tailorResultData;
  try {
    const resp = await fetch("/api/content/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        channel,
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
    applyStep4.scrollIntoView({ behavior: "smooth", block: "start" });
    loadDocList();
  } catch (e) {
    generateStatus.innerHTML = `<span class="apply-err">${e.message || "Generation failed"}</span>`;
  } finally {
    buttons.forEach(b => b.disabled = false);
  }
}

function renderDownloads(out) {
  const row = (item, label) => {
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

  applyDownloads.innerHTML =
    row(out.cv, "📄 CV") +
    row(out.letter, "✉️ Letter") +
    `<div class="fit-notes">Logged to Applications (📊 in the top bar). ` +
    `CV variant: <b>${escapeHTML(out.cv_variant)}</b>.</div>`;

  applyDownloads.querySelectorAll(".dl-open").forEach(btn => {
    btn.addEventListener("click", async () => {
      const path = btn.dataset.path;
      showView("edit");
      await loadDocList();
      await switchDocument(path, path.startsWith("letters/") ? "letter" : "cv");
    });
  });
}

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

(async function init() {
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
