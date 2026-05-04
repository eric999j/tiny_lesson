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
  - `settings.json`
  - `history.json`
  - `word_lookup_cache.json`
  - `tts_cache/*.mp3`
- Keep storage changes backward-compatible when possible; [app/storage.py](app/storage.py) already contains upgrade logic for older history entries.

## Working Conventions

- Keep user-facing text in Traditional Chinese unless the file already establishes another language requirement.
- Preserve the current separation of concerns: UI flow in [app/ui.py](app/ui.py), remote-call logic in [app/api_client.py](app/api_client.py), persistence in [app/storage.py](app/storage.py), and audio concerns in [app/tts.py](app/tts.py).
- Avoid moving API or file-system side effects into widget-building code unless the surrounding file already follows that pattern.
- When adding a language, update the entries in [app/config.py](app/config.py) and verify both prompt language name and gTTS language code remain valid.
- When changing model output structure, update both prompt instructions in [app/prompts.py](app/prompts.py) and parsers/normalizers in [app/api_client.py](app/api_client.py).

## Known Pitfalls

- Hugging Face calls may return slow-start or quota/model errors; keep error messages actionable in the UI.
- gTTS and playback both depend on the local environment and network/audio availability; prefer graceful failure paths over hard crashes.
- The UI uses background threads for long-running work. Keep Tkinter widget mutations on the main thread via `root.after(...)`.
- History, translations, and audio cache behavior are connected; when changing one, validate the others.

## Change Strategy

- Prefer small, local edits.
- If you change behavior in one of the core flows, verify the exact tab or action that owns that flow before editing adjacent modules.
- If more user documentation is needed, update [README.md](README.md) instead of expanding this file.