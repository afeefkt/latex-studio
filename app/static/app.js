// ── CodeMirror 6 via esm.sh ──────────────────────────────────────────────────
import { EditorView, basicSetup } from "https://esm.sh/codemirror@6.0.1";
import { EditorState }            from "https://esm.sh/@codemirror/state@^6.0.0?target=es2022";
import { keymap }                 from "https://esm.sh/@codemirror/view@^6.0.0?target=es2022";
import { defaultKeymap, indentWithTab } from "https://esm.sh/@codemirror/commands@^6.0.0?target=es2022";
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

  // Update download link
  btnDownload.href = `/api/pdf/${path}`;
  btnDownload.download = `${path}.pdf`;
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

// ── Init ──────────────────────────────────────────────────────────────────────

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
