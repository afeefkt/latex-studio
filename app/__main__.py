# ── Programmatic entry point — used by PyInstaller and `python -m app` ──

import threading
import webbrowser

import uvicorn

PORT = 8000


def _open_browser():
    import time
    time.sleep(1.2)
    webbrowser.open(f"http://127.0.0.1:{PORT}")


if __name__ == "__main__":
    threading.Thread(target=_open_browser, daemon=True).start()
    uvicorn.run("app.main:app", host="127.0.0.1", port=PORT, reload=False)
