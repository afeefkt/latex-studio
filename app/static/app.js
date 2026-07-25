// ── CodeMirror 6 via esm.sh ─────���─────────────────────────────────────────────
// Use the codemirror meta-package for basicSetup + EditorView (consistent internal deps).
// All sub-package imports use the same ?target=es2022 URL format so the browser
// module cache deduplicates @codemirror/state — avoiding the "multiple instances" error.
import { EditorView, basicSetup } from "https://esm.sh/codemirror@6.0.1";
import { EditorState }            from "https://esm.sh/@codemirror/state@^6.0.0?target=es2022";
import { keymap }                 from "https://esm.sh/@codemirror/view@^6.0.0?target=es2022";
import { defaultKeymap, indentWithTab } from "https://esm.sh/@codemirror/commands@^6.0.0?target=es2022";
import { oneDark }                from "https://esm.sh/@codemirror/theme-one-dark@^6.0.0?target=es2022";
import { StreamLanguage }         from "https://esm.sh/@codemirror/language@^6.0.0?target=es2022";
import { stex }                   from "https://esm.sh/@codemirror/legacy-modes/mode/stex?target=es2022";

// ── PDF.js via static import ──────────────────────────────────────────────────
const PDFJS_CDN = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.4.168";
const { getDocument, GlobalWorkerOptions } = await import(`${PDFJS_CDN}/pdf.min.mjs`);
GlobalWorkerOptions.workerSrc = `${PDFJS_CDN}/pdf.worker.min.mjs`;

// ── State ─────────────────────────────────────────────────────────────────────
const DOC_PATH = "cv";
let pdfDoc = null;
let currentPage = 1;
let zoomScale = 1.2;
let renderTask = null;
let debounceTimer = null;
const DEBOUNCE_MS = 1200;
let savedScrollTop = 0;
let savedScrollLeft = 0;

// ── DOM refs ──────────────────────────────────────────────────────────────────
const statusBadge    = document.getElementById("status-badge");
const errorList      = document.getElementById("error-list");
const pdfCanvas      = document.getElementById("pdf-canvas");
const pdfScroll      = document.getElementById("pdf-scroll-container");
const pdfPlaceholder = document.getElementById("pdf-placeholder");
const pageInfo       = document.getElementById("page-info");
const zoomLabel      = document.getElementById("zoom-label");
const btnPrev        = document.getElementById("btn-prev");
const btnNext        = document.getElementById("btn-next");
const btnZoomIn      = document.getElementById("btn-zoom-in");
const btnZoomOut     = document.getElementById("btn-zoom-out");
const btnFit         = document.getElementById("btn-fit");
const btnCompile     = document.getElementById("btn-compile");

// ── Load initial document content ────────────────────────────────────────────
let initialContent = "";
try {
  const resp = await fetch(`/api/docs/${DOC_PATH}?file=main.tex`);
  if (resp.ok) initialContent = await resp.text();
} catch (e) {
  console.warn("Could not load main.tex:", e);
}

// ── CodeMirror setup ──────────────────────────────────────────────────────────
const compileKeymap = keymap.of([
  { key: "Ctrl-Enter", run() { triggerCompile(); return true; } },
  { key: "Mod-Enter",  run() { triggerCompile(); return true; } },
]);

const view = new EditorView({
  state: EditorState.create({
    doc: initialContent,
    extensions: [
      basicSetup,
      oneDark,
      StreamLanguage.define(stex),
      keymap.of([...defaultKeymap, indentWithTab]),
      compileKeymap,
      EditorView.updateListener.of((update) => {
        if (update.docChanged) scheduleCompile();
      }),
      EditorView.theme({
        "&": { height: "100%", fontSize: "13px" },
        ".cm-scroller": { fontFamily: "'Cascadia Code','Fira Code','Consolas',monospace", overflow: "auto" },
        ".cm-content": { paddingBottom: "40px" },
      }),
    ],
  }),
  parent: document.getElementById("editor-container"),
});

// Make editor fill the pane
document.getElementById("editor-container").style.height = "100%";
// Sync zoom label with initial scale
zoomLabel.textContent = `${Math.round(zoomScale * 100)}%`;

// ── Compile ───────────────────────────────────────────────────────────────────
function scheduleCompile() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(triggerCompile, DEBOUNCE_MS);
}

async function triggerCompile() {
  clearTimeout(debounceTimer);
  savedScrollTop  = pdfScroll.scrollTop;
  savedScrollLeft = pdfScroll.scrollLeft;
  setStatus("compiling");

  const content = view.state.doc.toString();
  try {
    await fetch(`/api/docs/${DOC_PATH}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content, file: "main.tex" }),
    });
  } catch {
    setStatus("error");
    showErrors([{ file: "", line: null, message: "Network error saving file", kind: "error" }]);
    return;
  }

  let result;
  try {
    const resp = await fetch("/api/compile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: DOC_PATH }),
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
  const total = view.state.doc.lines;
  const line  = view.state.doc.line(Math.min(lineNumber, total));
  view.dispatch({
    selection: { anchor: line.from },
    effects: EditorView.scrollIntoView(line.from, { y: "center" }),
  });
  view.focus();
}

// ── PDF ───────────────────────────────────────────────────────────────────────
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
  btnPrev.disabled         = currentPage <= 1;
  btnNext.disabled         = !pdfDoc || currentPage >= pdfDoc.numPages;
}

// ── Controls ──────────────────────────────────────────────────────────────────
btnPrev.addEventListener("click", async () => {
  if (!pdfDoc || currentPage <= 1) return;
  currentPage--;
  await renderPage(currentPage);
  updatePageInfo();
});
btnNext.addEventListener("click", async () => {
  if (!pdfDoc || currentPage >= pdfDoc.numPages) return;
  currentPage++;
  await renderPage(currentPage);
  updatePageInfo();
});
btnZoomIn.addEventListener("click",  () => setZoom(zoomScale + 0.15));
btnZoomOut.addEventListener("click", () => setZoom(zoomScale - 0.15));
btnFit.addEventListener("click", fitWidth);
btnCompile.addEventListener("click", triggerCompile);

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

// ── Resize handle ─────────────────────────────────────────────────────────────
const handle     = document.getElementById("drag-handle");
const editorPane = document.getElementById("editor-pane");
const workspace  = document.getElementById("workspace");

handle.addEventListener("mousedown", (e) => {
  e.preventDefault();
  handle.classList.add("dragging");
  const onMove = (ev) => {
    const left  = workspace.getBoundingClientRect().left;
    const pct   = Math.max(20, Math.min(80, ((ev.clientX - left) / workspace.clientWidth) * 100));
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

// ── Initial PDF load (from a previous session's compiled output) ───────────────
try {
  const head = await fetch(`/api/pdf/${DOC_PATH}`, { method: "HEAD" });
  if (head.ok) {
    await loadPdf(`/api/pdf/${DOC_PATH}`);
    setStatus("ok");
  }
} catch (_) { /* no cached PDF yet — wait for first compile */ }
