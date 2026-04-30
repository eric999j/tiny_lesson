"""JSON-backed storage for settings and learning history."""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from . import tts
from .config import DEFAULT_LANGUAGES, HISTORY_FILE, SETTINGS_FILE, build_language_map, ensure_dirs


_EMPTY_HISTORY: dict[str, list[dict[str, Any]]] = {
    "words": [],
    "grammar": [],
    "sentences": [],
    "translations": [],
}


def _default_languages() -> list[dict[str, str]]:
    return [dict(entry) for entry in DEFAULT_LANGUAGES]


def normalize_languages(entries: Any) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    seen_display: set[str] = set()
    if not isinstance(entries, list):
        return normalized
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        display = str(entry.get("display", "")).strip()
        code = str(entry.get("code", "")).strip()
        name = str(entry.get("name", "")).strip()
        if not display or not code or not name or display in seen_display:
            continue
        seen_display.add(display)
        normalized.append({"display": display, "code": code, "name": name})
    return normalized


def get_language_entries(settings: dict[str, Any]) -> list[dict[str, str]]:
    if not isinstance(settings, dict):
        return _default_languages()
    if "languages" not in settings:
        return _default_languages()
    return normalize_languages(settings.get("languages", []))


def get_language_map(settings: dict[str, Any]) -> dict[str, tuple[str, str]]:
    return build_language_map(get_language_entries(settings))


def _playback_audio_ref(text: str, lang: str, slow: bool, role: str = "playback") -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    return tts.audio_ref(text=text, lang=lang, slow=slow, role=role)


def _item_audio_refs(item: dict[str, Any]) -> list[dict[str, Any]]:
    refs = item.get("audio_refs", [])
    if isinstance(refs, list):
        valid = [ref for ref in refs if isinstance(ref, dict) and ref.get("hash")]
        if valid:
            return valid
    fallback = item.get("playback_audio")
    if isinstance(fallback, dict) and fallback.get("hash"):
        return [fallback]
    return []


def _referenced_audio_hashes(history: dict[str, list[dict[str, Any]]]) -> set[str]:
    hashes: set[str] = set()
    for items in history.values():
        for item in items:
            for ref in _item_audio_refs(item):
                hashes.add(str(ref.get("hash")))
    return hashes


def _upgrade_item_audio(category: str, item: dict[str, Any]) -> bool:
    if item.get("playback_audio") and item.get("audio_refs"):
        return False
    lang = str(item.get("lang", "en"))
    refs: list[dict[str, Any]] = []
    if category == "grammar":
        example_ref = _playback_audio_ref(item.get("example", ""), lang, False, role="example")
        point_ref = _playback_audio_ref(item.get("point", ""), lang, False, role="point")
        refs = [ref for ref in [example_ref, point_ref] if ref]
        playback = example_ref or point_ref
    else:
        text_value = item.get("text", "")
        primary_ref = _playback_audio_ref(text_value, lang, False, role="text")
        refs = [primary_ref] if primary_ref else []
        playback = primary_ref
    if playback:
        item["playback_audio"] = playback
        item["audio_refs"] = refs
        return True
    return False


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write_json(path, data) -> None:
    ensure_dirs()
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    import os
    os.replace(tmp, path)


# ---------- settings ----------
def load_settings() -> dict[str, Any]:
    defaults = {
        "hf_token": "",
        "model": "",
        "tts_slow": False,
        "theme": "light",
        "languages": _default_languages(),
    }
    data = _read_json(SETTINGS_FILE, {})
    if not isinstance(data, dict):
        return {
            "hf_token": defaults["hf_token"],
            "model": defaults["model"],
            "tts_slow": defaults["tts_slow"],
            "theme": defaults["theme"],
            "languages": _default_languages(),
        }
    merged = defaults.copy()
    merged.update(data)
    merged["languages"] = get_language_entries(merged)
    return merged


def save_settings(data: dict[str, Any]) -> None:
    payload = dict(data)
    payload["languages"] = normalize_languages(payload.get("languages", []))
    _write_json(SETTINGS_FILE, payload)


# ---------- history ----------
def load_history() -> dict[str, list[dict[str, Any]]]:
    data = _read_json(HISTORY_FILE, None)
    if not isinstance(data, dict):
        return {k: [] for k in _EMPTY_HISTORY}
    changed = False
    for k in _EMPTY_HISTORY:
        data.setdefault(k, [])
        for item in data[k]:
            if isinstance(item, dict):
                changed = _upgrade_item_audio(k, item) or changed
    if changed:
        save_history(data)
    return data


def save_history(data: dict[str, list[dict[str, Any]]]) -> None:
    _write_json(HISTORY_FILE, data)


def _make_id(lang: str, text: str) -> str:
    return hashlib.sha1(f"{lang}|{text}".encode("utf-8")).hexdigest()[:16]


def add_batch(lang: str, scenario: str, payload: dict[str, list[dict[str, Any]]], slow: bool = False) -> dict[str, list[str]]:
    """Merge a generation result into history and return the ids added in this operation."""
    history = load_history()
    ts = int(time.time())
    added_ids: dict[str, list[str]] = {"words": [], "grammar": [], "sentences": [], "translations": []}

    def _index(items: list[dict[str, Any]]) -> set[str]:
        return {it.get("id", "") for it in items}

    for w in payload.get("words", []) or []:
        text = (w.get("text") or "").strip()
        if not text:
            continue
        item = {
            "id": _make_id(lang, "w:" + text),
            "ts": ts,
            "lang": lang,
            "scenario": scenario,
            "text": text,
            "translation": (w.get("translation") or "").strip(),
        }
        primary_audio = _playback_audio_ref(text, lang, slow, role="text")
        if primary_audio:
            item["playback_audio"] = primary_audio
            item["audio_refs"] = [primary_audio]
        if item["id"] not in _index(history["words"]):
            history["words"].append(item)
            added_ids["words"].append(item["id"])
            if primary_audio:
                try:
                    tts.synthesize_audio_ref(primary_audio)
                except Exception:
                    pass

    for g in payload.get("grammar", []) or []:
        point = (g.get("point") or "").strip()
        if not point:
            continue
        item = {
            "id": _make_id(lang, "g:" + point),
            "ts": ts,
            "lang": lang,
            "scenario": scenario,
            "point": point,
            "explanation": (g.get("explanation") or "").strip(),
            "example": (g.get("example") or "").strip(),
        }
        example_audio = _playback_audio_ref(item["example"], lang, slow, role="example")
        point_audio = _playback_audio_ref(point, lang, slow, role="point")
        audio_refs = [ref for ref in [example_audio, point_audio] if ref]
        playback_audio = example_audio or point_audio
        if playback_audio:
            item["playback_audio"] = playback_audio
            item["audio_refs"] = audio_refs
        if item["id"] not in _index(history["grammar"]):
            history["grammar"].append(item)
            added_ids["grammar"].append(item["id"])
            for ref in audio_refs:
                try:
                    tts.synthesize_audio_ref(ref)
                except Exception:
                    pass

    for s in payload.get("sentences", []) or []:
        text = (s.get("text") or "").strip()
        if not text:
            continue
        item = {
            "id": _make_id(lang, "s:" + text),
            "ts": ts,
            "lang": lang,
            "scenario": scenario,
            "text": text,
            "translation": (s.get("translation") or "").strip(),
        }
        primary_audio = _playback_audio_ref(text, lang, slow, role="text")
        if primary_audio:
            item["playback_audio"] = primary_audio
            item["audio_refs"] = [primary_audio]
        if item["id"] not in _index(history["sentences"]):
            history["sentences"].append(item)
            added_ids["sentences"].append(item["id"])
            if primary_audio:
                try:
                    tts.synthesize_audio_ref(primary_audio)
                except Exception:
                    pass

    save_history(history)
    return added_ids


def add_translation(
    lang: str,
    word: str,
    translation: str,
    slow: bool = False,
    reading: str = "",
    primary_note: str = "",
    alternatives: list[dict[str, str]] | None = None,
) -> dict[str, list[str]]:
    """Add a quick translation to history and return the ids added in this operation."""
    history = load_history()
    ts = int(time.time())
    normalized_alternatives: list[dict[str, str]] = []
    for alternative in alternatives or []:
        if not isinstance(alternative, dict):
            continue
        term = str(alternative.get("term", "")).strip()
        note = str(alternative.get("note", "")).strip()
        if term:
            normalized_alternatives.append({"term": term, "note": note})
    
    item = {
        "id": _make_id(lang, "t:" + word),
        "ts": ts,
        "lang": lang,
        "word": word,
        "translation": translation,
        "reading": reading,
        "primary_note": primary_note.strip(),
        "alternatives": normalized_alternatives,
        "scenario": "翻譯",  # Mark as quick translation
    }
    
    # Generate audio for the word
    primary_audio = _playback_audio_ref(word, lang, slow, role="word")
    if primary_audio:
        item["playback_audio"] = primary_audio
        item["audio_refs"] = [primary_audio]
        try:
            tts.synthesize_audio_ref(primary_audio)
        except Exception:
            pass
    
    for index, existing in enumerate(history["translations"]):
        if existing.get("id") == item["id"]:
            history["translations"][index] = item
            save_history(history)
            return {"words": [], "grammar": [], "sentences": [], "translations": []}

    history["translations"].append(item)
    save_history(history)
    return {"words": [], "grammar": [], "sentences": [], "translations": [item["id"]]}


def delete_items(category: str, item_ids: list[str]) -> int:
    history = load_history()
    if category not in history or not item_ids:
        return 0
    item_id_set = {item_id for item_id in item_ids if item_id}
    if not item_id_set:
        return 0
    removed_items = [it for it in history[category] if it.get("id") in item_id_set]
    if not removed_items:
        return 0
    removed_hashes: set[str] = set()
    for item in removed_items:
        for ref in _item_audio_refs(item):
            removed_hashes.add(str(ref.get("hash")))
    history[category] = [it for it in history[category] if it.get("id") not in item_id_set]
    save_history(history)
    remaining_hashes = _referenced_audio_hashes(history)
    for audio_hash in removed_hashes - remaining_hashes:
        tts.delete_cached_audio(audio_hash)
    return len(removed_items)


def delete_item(category: str, item_id: str) -> None:
    history = load_history()
    if category in history:
        to_remove = next((it for it in history[category] if it.get("id") == item_id), None)
        removed_hashes = {str(ref.get("hash")) for ref in _item_audio_refs(to_remove or {})}
        history[category] = [it for it in history[category] if it.get("id") != item_id]
        save_history(history)
        remaining_hashes = _referenced_audio_hashes(history)
        for audio_hash in removed_hashes - remaining_hashes:
            tts.delete_cached_audio(audio_hash)


def delete_scenario(category: str, scenario: str) -> int:
    history = load_history()
    if category not in history:
        return 0
    removed_items = [it for it in history[category] if (it.get("scenario", "未分類") or "未分類") == scenario]
    if not removed_items:
        return 0
    removed_hashes: set[str] = set()
    for item in removed_items:
        for ref in _item_audio_refs(item):
            removed_hashes.add(str(ref.get("hash")))
    history[category] = [
        it for it in history[category]
        if (it.get("scenario", "未分類") or "未分類") != scenario
    ]
    save_history(history)
    remaining_hashes = _referenced_audio_hashes(history)
    for audio_hash in removed_hashes - remaining_hashes:
        tts.delete_cached_audio(audio_hash)
    return len(removed_items)


def clear_history_category(category: str) -> None:
    history = load_history()
    if category not in history:
        return
    removed_hashes: set[str] = set()
    for item in history[category]:
        for ref in _item_audio_refs(item):
            removed_hashes.add(str(ref.get("hash")))
    history[category] = []
    save_history(history)
    remaining_hashes = _referenced_audio_hashes(history)
    for audio_hash in removed_hashes - remaining_hashes:
        tts.delete_cached_audio(audio_hash)


def clear_history() -> None:
    history = load_history()
    removed_hashes = _referenced_audio_hashes(history)
    save_history({k: [] for k in _EMPTY_HISTORY})
    for audio_hash in removed_hashes:
        tts.delete_cached_audio(audio_hash)
