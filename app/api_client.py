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


def _clean_translation_text(text: Any) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"^[Tt]ranslation[\s:]*", "", cleaned).strip()
    cleaned = re.sub(r"^翻譯[\s：:]*", "", cleaned).strip()
    cleaned = re.sub(r"^[Tt]he\s+translation\s+(is|of)?[\s]*", "", cleaned).strip()
    cleaned = re.sub(r"^means[\s]*", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = cleaned.split("(")[0].strip()
    cleaned = cleaned.split("。", 1)[0].strip()
    cleaned = cleaned.split(".", 1)[0].strip()
    return cleaned


def _contains_han(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def _contains_kana(text: str) -> bool:
    return bool(re.search(r"[\u3040-\u30ff]", text or ""))


def _describe_source_word(word: str) -> str:
    sample = str(word or "").strip()
    if not sample:
        return "source word"
    if _contains_han(sample) and not _contains_kana(sample):
        return "Chinese word"
    if _contains_kana(sample):
        return "Japanese word"
    if re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", sample):
        return "word"
    return "source word"


def _looks_like_target_language(text: str, target_language: str) -> bool:
    sample = str(text or "").strip()
    if not sample:
        return False

    normalized_target = target_language.strip().lower()
    if normalized_target in {"chinese", "traditional chinese", "simplified chinese", "中文", "漢語", "华语", "華語"}:
        return _contains_han(sample)
    if normalized_target in {"japanese", "日文", "日語", "日本語"}:
        return _contains_han(sample) or _contains_kana(sample)

    if _contains_han(sample) or _contains_kana(sample):
        return False

    return bool(re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", sample))


def _build_translate_messages(word: str, target_language: str, strict: bool, require_alternatives: bool) -> list[dict[str, str]]:
    source_label = _describe_source_word(word)
    extra_rules = ""
    if strict:
        extra_rules = "\n6. primary and every alternatives.term must be written ONLY in the target language."
        if source_label == "Chinese word":
            extra_rules += "\n7. The source word is Chinese. Do NOT paraphrase it in Chinese."
        if target_language.strip().lower() == "indonesian":
            extra_rules += "\n8. If the target language is Indonesian, valid outputs look like 'suka' or 'gemar', not Chinese characters."
        extra_rules += "\n9. Any Chinese characters in primary or alternatives.term are invalid unless the target language is Chinese or Japanese."
    if require_alternatives:
        extra_rules += (
            "\n10. If this word has contextual synonyms or register differences, you must include at least one alternative."
            "\n11. Prefer alternatives that are actually used in different scenarios, habits, strength, formality, or frequency."
        )

    user_prompt = (
        f"Translate the {source_label} '{word}' to {target_language}.\n\n"
        "Respond with ONLY a JSON object using this exact schema:\n"
        "{\n"
        '  "primary": "<best default translation in the target language>",\n'
        '  "primary_note": "<Traditional Chinese explanation of when this primary term is used>",\n'
        '  "reading": "<hiragana only if target language is Japanese, else empty string>",\n'
        '  "alternatives": [\n'
        '    {"term": "<contextual synonym in the target language>", "note": "<Traditional Chinese explanation of the nuance or scenario difference>"}\n'
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "1. Choose the most common neutral translation as primary.\n"
        "2. Include 1 to 4 alternatives when different contexts, tone, frequency, or nuance matter.\n"
        "3. All notes must be in Traditional Chinese.\n"
        "4. If there are no meaningful alternatives, return an empty array.\n"
        "5. Do not output markdown or any extra text."
        f"{extra_rules}"
    )
    system_prompt = (
        "You are a precise translator. The translation output must be in the requested target language only. "
        "Return ONLY valid JSON. Use Traditional Chinese only for explanation fields."
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


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


def _request_chat_content(
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: int,
) -> str:
    resp = requests.post(HF_ROUTER_URL, headers=headers, json=payload, timeout=timeout)
    if resp.status_code == 401:
        raise APIError("Hugging Face Token 無效 (401)。")
    if resp.status_code == 402:
        raise APIError("免費額度已用完或此模型需付費 (402)。")
    if resp.status_code == 404:
        raise APIError(f"找不到模型『{payload.get('model', '')}』(404)。")
    if resp.status_code >= 400:
        raise APIError(f"HF API 錯誤 {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    try:
        return str(data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError) as e:
        raise APIError(f"非預期回傳格式：{e}")


def _build_term_only_messages(word: str, target_language: str) -> list[dict[str, str]]:
    source_label = _describe_source_word(word)
    user_prompt = (
        f"Translate the {source_label} '{word}' to {target_language}.\n\n"
        "Respond with ONLY this JSON schema:\n"
        "{\n"
        '  "primary": "<target-language term>",\n'
        '  "alternatives": ["<target-language synonym>"]\n'
        "}\n\n"
        "Rules:\n"
        "1. primary and every alternatives item must be written ONLY in the target language.\n"
        "2. Do not use Chinese, Japanese, or explanations.\n"
        "3. Return 1 to 3 alternatives only when they are real contextual synonyms.\n"
        "4. If the target language is Portuguese, valid examples look like amor, gostar, adorar.\n"
        "5. If the target language is Indonesian, valid examples look like suka, gemar, menyukai.\n"
        "6. Return only JSON."
    )
    return [
        {
            "role": "system",
            "content": "You are a precise translator. Return only target-language terms as valid JSON.",
        },
        {"role": "user", "content": user_prompt},
    ]


def _build_explanation_messages(
    *,
    word: str,
    target_language: str,
    primary: str,
    alternatives: list[str],
) -> list[dict[str, str]]:
    term_list = [primary] + [term for term in alternatives if term and term != primary]
    user_prompt = (
        f"The source word is '{word}'. The target language is {target_language}.\n"
        f"Use these exact target-language terms: {', '.join(term_list)}.\n\n"
        "Respond with ONLY this JSON schema:\n"
        "{\n"
        '  "primary_note": "<Traditional Chinese explanation of the primary term>",\n'
        '  "alternatives": [\n'
        '    {"term": "<one of the exact target-language terms>", "note": "<Traditional Chinese nuance explanation>"}\n'
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "1. Do not change, translate, or transliterate the target-language terms.\n"
        "2. All notes must be in Traditional Chinese.\n"
        "3. alternatives.term must come from the provided target-language terms only.\n"
        "4. Return only JSON."
    )
    return [
        {
            "role": "system",
            "content": "You explain nuance differences between already-fixed translations. Keep the provided target-language terms unchanged and write explanations in Traditional Chinese.",
        },
        {"role": "user", "content": user_prompt},
    ]


def _fallback_translate_word(
    *,
    headers: dict[str, str],
    model: str,
    target_language: str,
    word: str,
    timeout: int,
) -> dict[str, Any]:
    term_payload = {
        "model": model,
        "messages": _build_term_only_messages(word, target_language),
        "temperature": 0.1,
        "max_tokens": 160,
        "stream": False,
    }
    term_content = _request_chat_content(headers=headers, payload=term_payload, timeout=timeout)
    parsed_terms = _extract_json(term_content)
    primary = _clean_translation_text(parsed_terms.get("primary", ""))
    if not _looks_like_target_language(primary, target_language):
        raise APIError(f"fallback 主翻譯仍不是目標語言：{primary} -> {target_language}")

    alternatives: list[str] = []
    raw_alternatives = parsed_terms.get("alternatives", []) or []
    if isinstance(raw_alternatives, list):
        for item in raw_alternatives:
            term = _clean_translation_text(item)
            if not term or term == primary:
                continue
            if _looks_like_target_language(term, target_language):
                alternatives.append(term)

    explanation_payload = {
        "model": model,
        "messages": _build_explanation_messages(
            word=word,
            target_language=target_language,
            primary=primary,
            alternatives=alternatives,
        ),
        "temperature": 0.2,
        "max_tokens": 220,
        "stream": False,
    }
    explanation_content = _request_chat_content(
        headers=headers,
        payload=explanation_payload,
        timeout=timeout,
    )
    parsed_explanation = _extract_json(explanation_content)
    primary_note = str(parsed_explanation.get("primary_note", "")).strip()
    alternative_notes: dict[str, str] = {}
    raw_note_items = parsed_explanation.get("alternatives", []) or []
    if isinstance(raw_note_items, list):
        for item in raw_note_items:
            if not isinstance(item, dict):
                continue
            term = _clean_translation_text(item.get("term", ""))
            note = str(item.get("note", "")).strip()
            if term and term in alternatives and note:
                alternative_notes[term] = note

    return {
        "text": primary,
        "reading": "",
        "primary_note": primary_note,
        "alternatives": [
            {"term": term, "note": alternative_notes.get(term, "")}
            for term in alternatives
        ],
    }


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
) -> dict[str, Any]:
    """Translate a word to the target language.

        Returns a dict with keys:
            - "text":         the primary translation word/phrase
            - "reading":      hiragana reading (non-empty only when target is Japanese)
            - "primary_note": Traditional Chinese explanation of the primary usage
            - "alternatives": list of contextual synonyms with usage notes
    """
    if not hf_token:
        raise APIError("尚未設定 Hugging Face API Token，請至『設定』分頁填入。")
    model = (model or DEFAULT_MODEL).strip()

    headers = {
        "Authorization": f"Bearer {hf_token}",
        "Content-Type": "application/json",
    }

    is_japanese = target_language.lower() in ("japanese", "日文", "日語", "日本語")

    payload = {
        "model": model,
        "messages": _build_translate_messages(word, target_language, strict=False, require_alternatives=False),
        "temperature": 0.3,
        "max_tokens": 260,
        "stream": False,
    }

    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            payload["messages"] = _build_translate_messages(
                word,
                target_language,
                strict=attempt > 1,
                require_alternatives=attempt > 1,
            )
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
            try:
                parsed = _extract_json(content)
            except APIError:
                parsed = None

            if isinstance(parsed, dict):
                primary = _clean_translation_text(parsed.get("primary", ""))
                primary_note = str(parsed.get("primary_note", "")).strip()
                reading = str(parsed.get("reading", "")).strip() if is_japanese else ""
                alternatives: list[dict[str, str]] = []
                raw_alternatives = parsed.get("alternatives", []) or []
                filtered_invalid_alternative = False
                if isinstance(raw_alternatives, list):
                    for alt in raw_alternatives:
                        if not isinstance(alt, dict):
                            continue
                        term = _clean_translation_text(alt.get("term", ""))
                        note = str(alt.get("note", "")).strip()
                        if not term:
                            continue
                        if term == primary and not primary_note and note:
                            primary_note = note
                            continue
                        if term == primary and not note:
                            continue
                        if not _looks_like_target_language(term, target_language):
                            filtered_invalid_alternative = True
                            continue
                        alternatives.append({"term": term, "note": note})

                if primary:
                    if not _looks_like_target_language(primary, target_language):
                        last_err = APIError(
                            f"模型回傳的主翻譯不是目標語言：{primary} -> {target_language}"
                        )
                        if attempt < retries:
                            continue
                        raise last_err
                    if filtered_invalid_alternative and not alternatives and attempt < retries:
                        continue
                    if not alternatives and attempt < retries:
                        continue
                    return {
                        "text": primary,
                        "reading": reading,
                        "primary_note": primary_note,
                        "alternatives": alternatives,
                    }

            m = re.match(r"^(.+?)\(([ぁ-ん]+)\)\s*$", content)
            if m:
                return {
                    "text": m.group(1).strip(),
                    "reading": m.group(2).strip(),
                    "primary_note": "",
                    "alternatives": [],
                }
            fallback_text = _clean_translation_text(content)
            if not _looks_like_target_language(fallback_text, target_language):
                last_err = APIError(
                    f"模型回傳的翻譯不是目標語言：{fallback_text} -> {target_language}"
                )
                if attempt < retries:
                    continue
                raise last_err
            return {
                "text": fallback_text,
                "reading": "",
                "primary_note": "",
                "alternatives": [],
            }
        except requests.RequestException as e:
            last_err = APIError(f"網路錯誤: {e}")
            time.sleep(1 * attempt)
        except APIError as e:
            last_err = e
            if "503" not in str(e) or attempt >= retries:
                break
    if last_err and "目標語言" in str(last_err):
        return _fallback_translate_word(
            headers=headers,
            model=model,
            target_language=target_language,
            word=word,
            timeout=timeout,
        )

    raise last_err or APIError("翻譯失敗")
