"""Configuration: paths and language map."""
from __future__ import annotations

import os
from pathlib import Path


APP_NAME = "TinyLesson"


def _appdata_dir() -> Path:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return Path(base) / APP_NAME


DATA_DIR: Path = _appdata_dir()
CACHE_DIR: Path = DATA_DIR / "tts_cache"
HISTORY_FILE: Path = DATA_DIR / "history.json"
SETTINGS_FILE: Path = DATA_DIR / "settings.json"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


# Language entries: display label + gTTS code + prompt language name.
DEFAULT_LANGUAGES: list[dict[str, str]] = [
    {"display": "英文 (English)", "code": "en", "name": "English"},
    {"display": "印尼文 (Bahasa Indonesia)", "code": "id", "name": "Indonesian"},
    {"display": "日文 (日本語)", "code": "ja", "name": "Japanese"},
    {"display": "葡萄牙文 (Português)", "code": "pt", "name": "Portuguese"},
]


def build_language_map(entries: list[dict[str, str]]) -> dict[str, tuple[str, str]]:
    language_map: dict[str, tuple[str, str]] = {}
    for entry in entries:
        display = entry.get("display", "").strip()
        code = entry.get("code", "").strip()
        name = entry.get("name", "").strip()
        if display and code and name:
            language_map[display] = (code, name)
    return language_map


LANGUAGES: dict[str, tuple[str, str]] = build_language_map(DEFAULT_LANGUAGES)


DEFAULT_MODEL = "Qwen/Qwen2.5-7B-Instruct"

AVAILABLE_MODELS: list[str] = [
    "Qwen/Qwen2.5-7B-Instruct",
    "Qwen/Qwen2.5-72B-Instruct",
    "meta-llama/Llama-3.3-70B-Instruct",
    "meta-llama/Llama-3.1-8B-Instruct",
    "mistralai/Mistral-7B-Instruct-v0.3",
    "mistralai/Mixtral-8x7B-Instruct-v0.1",
    "google/gemma-2-9b-it",
    "HuggingFaceH4/zephyr-7b-beta",
]
