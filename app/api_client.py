"""Hugging Face Inference Providers (OpenAI-compatible) client."""
from __future__ import annotations

import json
import re
import time
from typing import Any

import requests

from .config import DEFAULT_MODEL
from .prompts import SYSTEM_INSTRUCTION


HF_ROUTER_URL = "https://router.huggingface.co/v1/chat/completions"


class APIError(Exception):
    pass


def _extract_json(text: str) -> dict[str, Any]:
    if not text:
        raise APIError("Empty response from model")
    # remove ```json fences if present
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", text, flags=re.IGNORECASE)
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise APIError(f"模型輸出找不到 JSON：{text[:200]}")
    raw = match.group(0)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise APIError(f"JSON 解析失敗：{e}\n---\n{raw[:400]}")


def generate_lesson(
    *,
    hf_token: str,
    model: str | None,
    target_language: str,
    scenario: str,
    timeout: int = 90,
    retries: int = 3,
) -> dict[str, list[dict[str, Any]]]:
    if not hf_token:
        raise APIError("尚未設定 Hugging Face API Token，請至『設定』分頁填入。")
    model = (model or DEFAULT_MODEL).strip()

    headers = {
        "Authorization": f"Bearer {hf_token}",
        "Content-Type": "application/json",
    }
    user_prompt = (
        f"TARGET LANGUAGE: {target_language}\n"
        f"SCENARIO: {scenario}\n\n"
        f"Respond with ONLY the JSON object."
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_INSTRUCTION},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 1200,
        "stream": False,
    }

    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(
                HF_ROUTER_URL, headers=headers, json=payload, timeout=timeout
            )
            if resp.status_code == 503:
                last_err = APIError(f"模型載入中 (503)，第 {attempt} 次重試…")
                time.sleep(3 * attempt)
                continue
            if resp.status_code == 401:
                raise APIError(
                    "Hugging Face Token 無效 (401)。請確認 Token 並有勾選 "
                    "『Make calls to Inference Providers』權限。"
                )
            if resp.status_code == 402:
                raise APIError(
                    "免費額度已用完或此模型需付費 (402)。請改用其他模型，"
                    "例如 Qwen/Qwen2.5-7B-Instruct。"
                )
            if resp.status_code == 404:
                raise APIError(
                    f"找不到模型『{model}』(404)。\n"
                    "請確認：\n"
                    "1. 模型名稱拼寫正確（格式 owner/name）\n"
                    "2. 該模型有支援 Inference Providers\n"
                    "3. 若為 gated 模型需先到模型頁面同意條款\n"
                    "建議改用：meta-llama/Llama-3.3-70B-Instruct 或 "
                    "Qwen/Qwen2.5-7B-Instruct 或 mistralai/Mistral-7B-Instruct-v0.3"
                )
            if resp.status_code >= 400:
                raise APIError(f"HF API 錯誤 {resp.status_code}: {resp.text[:300]}")

            data = resp.json()
            try:
                content = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as e:
                raise APIError(f"非預期回傳格式：{e}\n{str(data)[:300]}")

            parsed = _extract_json(content or "")
            return {
                "words": parsed.get("words", []) or [],
                "grammar": parsed.get("grammar", []) or [],
                "sentences": parsed.get("sentences", []) or [],
            }
        except requests.RequestException as e:
            last_err = APIError(f"網路錯誤: {e}")
            time.sleep(2 * attempt)
        except APIError as e:
            last_err = e
            msg = str(e)
            # only retry on transient 503
            if "503" not in msg or attempt >= retries:
                break

    raise last_err or APIError("未知錯誤")


def translate_word(
    *,
    hf_token: str,
    model: str | None,
    target_language: str,
    word: str,
    timeout: int = 30,
    retries: int = 2,
) -> dict[str, str]:
    """Translate a word to the target language.

    Returns a dict with keys:
      - "text":    the translated word/phrase
      - "reading": hiragana reading (non-empty only when target is Japanese)
    """
    if not hf_token:
        raise APIError("尚未設定 Hugging Face API Token，請至『設定』分頁填入。")
    model = (model or DEFAULT_MODEL).strip()

    headers = {
        "Authorization": f"Bearer {hf_token}",
        "Content-Type": "application/json",
    }

    is_japanese = target_language.lower() in ("japanese", "日文", "日語", "日本語")

    if is_japanese:
        user_prompt = (
            f"Translate '{word}' to Japanese.\n\n"
            f"Rules:\n"
            f"1. Respond with ONLY this exact format: kanji(hiragana)\n"
            f"2. Example: 母の日(ははのひ)\n"
            f"3. Do NOT include any other text\n\n"
            f"Translation:"
        )
    else:
        user_prompt = (
            f"Translate '{word}' to {target_language}.\n\n"
            f"Rules:\n"
            f"1. Respond with ONLY the translation word\n"
            f"2. Do NOT include any explanation, sentence structure, or additional text\n"
            f"3. Do NOT include phrases like 'the translation is', 'means', or 'is'\n\n"
            f"Translation:"
        )
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are a precise translator. Respond with ONLY the translated word or phrase in the requested target language. Never add explanations, examples, or any other text.",
            },
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 100,
        "stream": False,
    }

    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(
                HF_ROUTER_URL, headers=headers, json=payload, timeout=timeout
            )
            if resp.status_code == 503:
                last_err = APIError(f"模型載入中 (503)，第 {attempt} 次重試…")
                time.sleep(2 * attempt)
                continue
            if resp.status_code == 401:
                raise APIError("Hugging Face Token 無效 (401)。")
            if resp.status_code == 402:
                raise APIError("免費額度已用完或此模型需付費 (402)。")
            if resp.status_code == 404:
                raise APIError(f"找不到模型『{model}』(404)。")
            if resp.status_code >= 400:
                raise APIError(f"HF API 錯誤 {resp.status_code}: {resp.text[:300]}")

            data = resp.json()
            try:
                content = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as e:
                raise APIError(f"非預期回傳格式：{e}")

            content = content.strip()
            # Parse kanji(hiragana) format for Japanese
            import re as _re
            m = _re.match(r"^(.+?)\(([ぁ-ん]+)\)\s*$", content)
            if m:
                return {"text": m.group(1).strip(), "reading": m.group(2).strip()}
            return {"text": content, "reading": ""}
        except requests.RequestException as e:
            last_err = APIError(f"網路錯誤: {e}")
            time.sleep(1 * attempt)
        except APIError as e:
            last_err = e
            if "503" not in str(e) or attempt >= retries:
                break

    raise last_err or APIError("翻譯失敗")
