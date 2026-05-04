---
name: tiny-lesson-manual-validation
description: 'Run the Tiny Lesson validation checklist after modifying Tkinter UI, quick translation, lesson generation, history storage, settings persistence, or TTS playback. Use for app/ui.py, app/api_client.py, app/storage.py, app/tts.py, app/config.py, app/prompts.py, or main.py changes.'
argument-hint: 'Describe the changed flow, for example: quick translation, history delete, or settings persistence'
---

# Tiny Lesson Manual Validation

Use this skill whenever a task changes the desktop UI, translation flow, lesson generation, history behavior, TTS playback, settings persistence, or any shared logic behind those flows.

## Goals

- Apply the same validation standard every time.
- Run the cheapest executable sanity check first.
- Map changed files to the exact user flows that must be checked.
- Do not claim full validation if the UI checks were not actually performed.

## Flow Mapping

- `app/ui.py`: Learn tab, quick translation, history tab, settings tab, render logic, worker-thread handoff.
- `app/api_client.py` or `app/prompts.py`: lesson generation and quick translation responses.
- `app/storage.py`: settings persistence, history writes, history deletion, cache references.
- `app/tts.py`: audio generation, playback, cache cleanup, audio errors.
- `app/config.py`: language/model options and app data paths.
- `main.py`: startup behavior.

## Validation Procedure

1. Identify which user flows are affected from the changed files.
2. Run one narrow executable check first.
   Preferred options:
   - `get_errors` on the touched Python files.
   - A narrow Python syntax/import sanity check such as `python -m py_compile ...` for the touched files.
3. Run or report the manual checklist only for the affected flows.
4. In the final response, separate:
   - executable checks actually run
   - manual checks actually run
   - manual checks still required from the user
   - blockers such as missing HF token, network, or audio device

## Manual Checklist By Flow

### Learn Tab

- Launch the app with `python main.py`.
- Generate a lesson for one realistic scenario.
- Confirm words, grammar, and sentences all render.
- Confirm status text reflects success or a handled failure.

### Quick Translation

- Enter `/word` in the Learn tab.
- Confirm the translation view renders the primary translation, reading, and notes when applicable.
- Confirm a translation history entry is created or updated correctly.

### Audio

- Trigger TTS from newly generated or replayed content.
- Confirm playback works, or the app shows a handled error instead of crashing.
- If cache logic changed, confirm replay still works after the first generation.

### Settings

- Save any changed token, model, language, theme, or TTS-slow setting.
- Restart the app if persistence behavior was touched.
- Confirm the saved values are restored.

### History

- Confirm new generation or translation items appear in history.
- Replay one stored item.
- Delete one relevant item and confirm the UI stays consistent.

## Reporting Rules

- If only executable checks were run, say manual UI validation is still pending.
- If a flow was not affected, omit it from the checklist instead of dumping the full list.
- When translation or history behavior changes, mention the coupling explicitly because those flows share storage and cached audio references.