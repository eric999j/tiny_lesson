# AGENTS.md

Guidance for AI coding agents working in this repository.

## Project Scope

- Desktop app built with Python + Tkinter.
- Entry point is [main.py](main.py). The app launches the UI and does not expose a CLI beyond `python main.py`.
- Prefer linking to [README.md](README.md) for installation, token setup, and end-user troubleshooting instead of duplicating those instructions.

## Environment

- Python 3.10+.
- Typical setup on Windows PowerShell:
  - `python -m venv .venv`
  - `.\.venv\Scripts\Activate.ps1`
  - `pip install -r requirements.txt`
- Runtime dependencies are listed in [requirements.txt](requirements.txt).

## Run And Validate

- Start the app with `python main.py`.
- There is currently no automated test suite in the repository.
- Validate changes with focused manual checks in the running UI:
  - Learn tab: generate a lesson for a scenario and confirm words, grammar, and sentences render.
  - Quick translation: enter `/word` and confirm the translation view and history entry update.
  - Audio: trigger TTS and confirm playback or a handled error message.
  - Settings: save token, model, theme, or language changes and confirm they persist.
  - History: confirm new items appear, can be replayed, and can be removed cleanly.
- Detailed flow-to-check mapping and reporting rules live in [.github/skills/tiny-lesson-manual-validation/SKILL.md](.github/skills/tiny-lesson-manual-validation/SKILL.md). Apply it after any change to `app/**/*.py` or `main.py`.

## Architecture

- [main.py](main.py): minimal entry point that calls `app.ui.run()`.
- [app/ui.py](app/ui.py): main Tkinter controller, three tabs, user actions, background threads, and render logic.
- [app/api_client.py](app/api_client.py): Hugging Face chat-completions client, prompt assembly, response parsing, and translation helpers.
- [app/storage.py](app/storage.py): JSON-backed settings/history persistence and audio reference bookkeeping.
- [app/tts.py](app/tts.py): gTTS synthesis, pygame playback, and cache file handling.
- [app/config.py](app/config.py): app data paths, default languages, and model list.
- [app/prompts.py](app/prompts.py): prompt text and output-shape constraints for model calls.
- [app/theme.py](app/theme.py): theme constants and style application.

## Data And State

- Persistent app data is stored under `%APPDATA%/TinyLesson` on Windows.
- Important files managed there:
  - `settings.json` – user preferences and language list.
  - `history.json` – learn/translation history plus audio refs.
  - `lesson_cache.json` – offline lesson payloads keyed by `(lang, normalized scenario)`; used when Learn tab has no HF token or the same scenario is generated again.
  - `word_lookup_cache.json` – hover/quick-translate results keyed by `(word, lang)`; payload keys are `translation`, `reading`, `primary_note`, `alternatives`.
  - `tts_cache/*.mp3` – content-hashed audio; entries are reference-counted through `history.json` and pruned on delete.
- Keep storage changes backward-compatible when possible; [app/storage.py](app/storage.py) already contains upgrade logic for older history entries (see `_upgrade_item_audio`, gated by `_history_upgrade_done`).

## Working Conventions

- Keep user-facing text in Traditional Chinese unless the file already establishes another language requirement.
- Preserve the current separation of concerns: UI flow in [app/ui.py](app/ui.py), remote-call logic in [app/api_client.py](app/api_client.py), persistence in [app/storage.py](app/storage.py), and audio concerns in [app/tts.py](app/tts.py).
- Avoid moving API or file-system side effects into widget-building code unless the surrounding file already follows that pattern.
- When adding a language, update the entries in [app/config.py](app/config.py) and verify both prompt language name and gTTS language code remain valid.
- When changing model output structure, update both prompt instructions in [app/prompts.py](app/prompts.py) and parsers/normalizers in [app/api_client.py](app/api_client.py).
- Any blocking work (HF calls, JSON writes, gTTS synth, pygame init) belongs on a worker thread; hand off UI mutations via `self.root.after(0, ...)`. Detailed rules and the canonical worker pattern live in [.github/instructions/tkinter-threading.instructions.md](.github/instructions/tkinter-threading.instructions.md).

## Caching And Invariants

The UI reads through several caches. Missing an invalidation call is the most common source of stale views:

- **History (UI-side, in `TinyLessonApp`)** – `self._history_cache` plus `self._history_haystack_cache`. Any code path that writes history through `app/storage.py` (add_batch, add_translation, delete_item(s), delete_scenario, clear_history_category, clear_history) must be followed by `self._invalidate_history_cache()` before the next `_refresh_history()` / `_get_history()`. Worker threads should schedule the invalidate via `self.root.after(0, self._invalidate_history_cache)`.
- **Lesson cache (module-level in `app/storage.py`)** – `load_lesson_cache()` returns an in-memory dict guarded by the file's mtime; `save_cached_lesson` / `clear_lesson_cache` update the in-memory copy in sync with the write. Do not bypass these helpers to hand-edit `lesson_cache.json`.
- **Word lookup cache (`_word_translation_cache`)** – loaded async on startup, guarded by `self._word_cache_lock`, and flushed to disk via `_schedule_word_cache_persist` (debounced, ~500 ms). `_on_close` force-flushes any pending write; do not remove that flush. Callers should keep using `_store_word_translation_cache` / `_lookup_word_translation_cache` rather than touching the dict directly.
- **gTTS language table (`app/tts.py`)** – `supported_language_codes()` and `normalize_language_code()` share module caches (`_lang_cache`, `_normalize_cache`). No invalidation is expected at runtime; if you ever mutate them, do it inside the module.

## Keyboard Shortcuts

Bound globally in `TinyLessonApp._bind_shortcuts`. Keep them working when refactoring event handling:

- `Ctrl+Enter` – jump to Learn tab and trigger generate/translate.
- `Ctrl+Z` / `Ctrl+Shift+Z` – undo last generate/translate batch (`_undo_last_action`).
- `F5` – jump to History tab, invalidate + refresh.
- `Ctrl+F` – jump to History tab and focus the search entry.
- `Esc` – close the floating word tooltip.

## Known Pitfalls

- Hugging Face calls may return slow-start or quota/model errors; keep error messages actionable in the UI.
- gTTS and playback both depend on the local environment and network/audio availability; prefer graceful failure paths over hard crashes.
- The UI uses background threads for long-running work. Keep Tkinter widget mutations on the main thread via `root.after(...)`.
- History, translations, and audio cache behavior are connected; when changing one, validate the others.

## Change Strategy

- Prefer small, local edits.
- If you change behavior in one of the core flows, verify the exact tab or action that owns that flow before editing adjacent modules.
- If more user documentation is needed, update [README.md](README.md) instead of expanding this file.