---
description: "Use when editing Python files in this Tkinter desktop app, especially UI handlers, background threads, translation flows, history updates, or TTS callbacks. Covers Tkinter thread safety and root.after handoff rules."
name: "Tkinter Threading Guardrails"
applyTo: "main.py, app/**/*.py"
---

# Tkinter Threading Guardrails

- Treat Tkinter widgets, `StringVar`, notebook tabs, and message boxes as main-thread-only state.
- Do not update widgets or Tkinter variables from worker threads. Schedule UI work back to the main loop with `root.after(0, ...)`.
- Put network, storage, and TTS work off the UI thread when they can block. In this project that usually means Hugging Face calls, JSON persistence, or audio generation/playback setup.
- Keep the `root.after(...)` callback small. Compute data in the worker, then hand off only the render/status update to the main thread.
- If a worker needs to trigger several UI updates, prefer one main-thread callback that calls an existing renderer/helper instead of scattering multiple widget mutations across the worker.
- When changing quick translation, history, or audio flows, verify the full cross-module path instead of only the file you touched: `app/ui.py` + `app/api_client.py` + `app/storage.py` + `app/tts.py`.
- Preserve graceful error handling. Worker exceptions should end in a main-thread status update or dialog, not a silent failure or direct Tkinter call from the worker.

Example pattern:

```python
def _worker():
    try:
        result = api_client.fetch(...)
        self.root.after(0, self._render_result, result)
    except Exception as exc:
        self.root.after(0, self.status_var.set, f"❌ {exc}")
```