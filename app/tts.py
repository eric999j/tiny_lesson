"""TTS module: generate speech with gTTS, play with pygame."""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Any

from .config import CACHE_DIR, ensure_dirs


_lock = threading.Lock()
_mixer_ready = False


def supported_language_codes() -> dict[str, str]:
    try:
        from gtts.lang import tts_langs
    except ImportError as e:
        raise RuntimeError(
            "缺少 gTTS 套件。請在終端機執行：\n"
            "    pip install gTTS pygame\n"
            "（或於專案資料夾執行 pip install -r requirements.txt）"
        ) from e
    return tts_langs()


def normalize_language_code(lang: str) -> str:
    code = (lang or "").strip()
    if not code:
        raise RuntimeError("TTS 語言代碼不可空白。")
    supported = supported_language_codes()
    if code in supported:
        return code
    lower_index = {item.lower(): item for item in supported}
    canonical = lower_index.get(code.lower())
    if canonical:
        return canonical
    examples = ", ".join(sorted([item for item in ["en", "id", "ja", "pt", "zh-CN", "zh-TW"] if item in supported]))
    raise RuntimeError(f"TTS 語言代碼 '{code}' 不受 gTTS 支援。可參考：{examples}")


def _init_mixer() -> bool:
    global _mixer_ready
    if _mixer_ready:
        return True
    try:
        import pygame
        pygame.mixer.init()
        _mixer_ready = True
        return True
    except Exception:
        return False


def _cache_path(text: str, lang: str, slow: bool) -> Path:
    key = hashlib.sha1(f"{lang}|{int(slow)}|{text}".encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{key}.mp3"


def audio_ref(text: str, lang: str, slow: bool = False, role: str = "playback") -> dict[str, Any]:
    canonical_lang = normalize_language_code(lang)
    path = _cache_path(text, canonical_lang, slow)
    return {
        "hash": path.stem,
        "text": text,
        "lang": canonical_lang,
        "slow": bool(slow),
        "role": role,
    }


def cache_path_from_hash(audio_hash: str) -> Path:
    return CACHE_DIR / f"{audio_hash}.mp3"


def synthesize_audio_ref(ref: dict[str, Any]) -> Path:
    return synthesize(
        str(ref.get("text", "")),
        str(ref.get("lang", "en")),
        slow=bool(ref.get("slow", False)),
    )


def synthesize(text: str, lang: str, slow: bool = False) -> Path:
    """Return path to mp3, generating via gTTS if not cached."""
    ensure_dirs()
    canonical_lang = normalize_language_code(lang)
    path = _cache_path(text, canonical_lang, slow)
    if path.exists() and path.stat().st_size > 0:
        return path
    try:
        from gtts import gTTS
    except ImportError as e:
        raise RuntimeError(
            "缺少 gTTS 套件。請在終端機執行：\n"
            "    pip install gTTS pygame\n"
            "（或於專案資料夾執行 pip install -r requirements.txt）"
        ) from e
    tts = gTTS(text=text, lang=canonical_lang, slow=slow)
    tmp = path.with_suffix(".mp3.tmp")
    tts.save(str(tmp))
    tmp.replace(path)
    return path


def play_async(text: str, lang: str, slow: bool = False, on_error=None) -> None:
    """Synthesize (if needed) and play in a background thread."""
    def _run():
        try:
            path = synthesize(text, lang, slow)
            with _lock:
                if not _init_mixer():
                    raise RuntimeError("無法初始化音訊裝置 (pygame mixer)")
                import pygame
                pygame.mixer.music.stop()
                pygame.mixer.music.load(str(path))
                pygame.mixer.music.play()
        except Exception as e:
            if on_error:
                try:
                    on_error(e)
                except Exception:
                    pass
    threading.Thread(target=_run, daemon=True).start()


def play_audio_ref_async(ref: dict[str, Any], on_error=None) -> None:
    """Play audio for a previously stored audio reference."""

    def _run():
        try:
            path = synthesize_audio_ref(ref)
            with _lock:
                if not _init_mixer():
                    raise RuntimeError("無法初始化音訊裝置 (pygame mixer)")
                import pygame
                pygame.mixer.music.stop()
                pygame.mixer.music.load(str(path))
                pygame.mixer.music.play()
        except Exception as e:
            if on_error:
                try:
                    on_error(e)
                except Exception:
                    pass

    threading.Thread(target=_run, daemon=True).start()


def delete_cached_audio(audio_hash: str) -> None:
    path = cache_path_from_hash(audio_hash)
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass


def stop() -> None:
    if _mixer_ready:
        try:
            import pygame
            pygame.mixer.music.stop()
        except Exception:
            pass
