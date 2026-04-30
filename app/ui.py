"""Tkinter UI for Tiny Lesson."""
from __future__ import annotations

import copy
import json
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import api_client, storage, tts
from .config import AVAILABLE_MODELS, DEFAULT_MODEL, WORD_LOOKUP_CACHE_FILE, ensure_dirs
from .theme import (
    DEFAULT_THEME,
    PAD,
    THEME_LABEL_BY_NAME,
    THEME_NAME_BY_LABEL,
    THEME_OPTIONS,
    WINDOW_GEOMETRY,
    ThemeManager,
)


def _fmt_ts(ts: int) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
    except Exception:
        return str(ts)


class TinyLessonApp:
    def __init__(self, root: tk.Tk) -> None:
        ensure_dirs()
        self.root = root
        self.root.title("Tiny Lesson – 語言學習")
        self.settings = storage.load_settings()
        self.languages = storage.get_language_map(self.settings)
        self.language_entries = storage.get_language_entries(self.settings)
        self.theme = ThemeManager(root, self.settings.get("theme", DEFAULT_THEME))
        self.root.geometry(WINDOW_GEOMETRY)
        self.current_payload: dict | None = None
        self.current_translation: dict | None = None
        self.current_lang_code = ""
        self.undo_stack: list[dict] = []
        self._word_tooltip_win: tk.Toplevel | None = None
        self._word_tooltip_after_id: str | None = None
        self._word_cache_lock = threading.Lock()
        self._word_translation_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._load_word_translation_cache()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True)

        self.learn_tab = ttk.Frame(self.notebook)
        self.history_tab = ttk.Frame(self.notebook)
        self.settings_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.learn_tab, text="📚 學習")
        self.notebook.add(self.history_tab, text="🕘 歷史")
        self.notebook.add(self.settings_tab, text="⚙ 設定")

        self._build_learn_tab()
        self._build_history_tab()
        self._build_settings_tab()
        self._refresh_language_selector()
        self._apply_theme()

        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    # ---------- learn tab ----------
    def _build_learn_tab(self) -> None:
        top = ttk.Frame(self.learn_tab)
        top.pack(fill="x", padx=PAD, pady=PAD)

        ttk.Label(top, text="語言：").grid(row=0, column=0, sticky="w")
        initial_languages = list(self.languages.keys())
        self.lang_var = tk.StringVar(value=initial_languages[0] if initial_languages else "")
        self.lang_combo = ttk.Combobox(
            top, textvariable=self.lang_var,
            values=initial_languages, state="readonly" if initial_languages else "disabled", width=22,
        )
        self.lang_combo.grid(row=0, column=1, padx=(0, PAD))

        ttk.Label(top, text="情境：").grid(row=0, column=2, sticky="w")
        self.scenario_var = tk.StringVar()
        scenario_entry = ttk.Entry(top, textvariable=self.scenario_var, width=40)
        scenario_entry.grid(row=0, column=3, padx=(0, PAD), sticky="ew")
        scenario_entry.bind("<Return>", lambda _e: self._on_generate())
        scenario_entry.bind("<KeyRelease>", self._on_scenario_changed)

        actions = ttk.Frame(top, style="Surface.TFrame")
        actions.grid(row=0, column=4, sticky="n")

        self.undo_btn = ttk.Button(actions, text="↩ 回退上一步", command=self._undo_last_action, state="disabled")
        self.undo_btn.pack(fill="x", pady=(0, 6))

        self.generate_btn = ttk.Button(actions, text="生成", command=self._on_generate)
        self.generate_btn.pack(fill="x")
        self.generate_btn.configure(style="Accent.TButton")

        top.columnconfigure(3, weight=1)

        # Hint label for "/" translation usage
        self.hint_var = tk.StringVar(value="輸入 /[字詞] 按『翻譯』快速翻譯。")
        ttk.Label(self.learn_tab, textvariable=self.hint_var, style="Status.TLabel").pack(
            fill="x", padx=PAD
        )

        self.status_var = tk.StringVar(value="或輸入情境後按『生成』。例如：在咖啡店點一杯拿鐵。")
        ttk.Label(self.learn_tab, textvariable=self.status_var, style="Status.TLabel").pack(
            fill="x", padx=PAD
        )

        # scrollable result area
        container = ttk.Frame(self.learn_tab, style="Surface.TFrame")
        container.pack(fill="both", expand=True, padx=PAD, pady=PAD)
        self.canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=self.canvas.yview)
        self.results_frame = ttk.Frame(self.canvas, style="Surface.TFrame")
        self.results_frame.bind(
            "<Configure>",
            lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self._win_id = self.canvas.create_window((0, 0), window=self.results_frame, anchor="nw")
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfigure(self._win_id, width=e.width),
        )
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self._refresh_language_selector(show_status=False)

    def _on_scenario_changed(self, event=None) -> None:
        """Monitor scenario entry for '/' separator and update button text."""
        scenario = self.scenario_var.get()
        has_slash = "/" in scenario
        if has_slash:
            self.generate_btn.configure(text="翻譯")
        else:
            self.generate_btn.configure(text="生成")

    def _on_mousewheel(self, event) -> None:
        if self.notebook.index(self.notebook.select()) != 0:
            return
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _clear_results(self) -> None:
        self._hide_word_tooltip()
        for child in self.results_frame.winfo_children():
            child.destroy()

    def _on_generate(self) -> None:
        if not self.languages:
            messagebox.showwarning("缺少語言", "目前沒有可用語言，請先到『設定』新增至少一種語言。")
            self.notebook.select(self.settings_tab)
            return
        scenario = self.scenario_var.get().strip()
        if not scenario:
            messagebox.showinfo("提示", "請輸入情境")
            return
        
        lang_display = self.lang_var.get()
        if lang_display not in self.languages:
            messagebox.showwarning("語言無效", "目前選取的語言不存在，請重新選擇或到『設定』檢查語言清單。")
            self._refresh_language_selector()
            self.notebook.select(self.settings_tab)
            return
        lang_code, lang_name = self.languages[lang_display]
        try:
            lang_code = tts.normalize_language_code(lang_code)
        except RuntimeError as e:
            messagebox.showwarning("語言代碼無效", f"{e}\n請到『設定』修正這個語言的 TTS 代碼。")
            self.notebook.select(self.settings_tab)
            return

        token = self.settings.get("hf_token", "").strip()
        if not token:
            messagebox.showwarning("缺少 Token", "請先到『設定』填入 Hugging Face API Token。")
            self.notebook.select(self.settings_tab)
            return
        previous_state = self._snapshot_current_state()

        # Check if this is a quick translation mode: /[word]
        if scenario.startswith("/"):
            word_to_translate = scenario[1:].strip()
            if not word_to_translate:
                messagebox.showinfo("提示", "請輸入要翻譯的字詞。格式：/[字詞]")
                return
            
            self.generate_btn.configure(state="disabled")
            self.status_var.set("⏳ 翻譯中…")
            self._clear_results()
            model = self.settings.get("model", "").strip() or DEFAULT_MODEL

            def _translate_work():
                try:
                    result = api_client.translate_word(
                        hf_token=token,
                        model=model,
                        target_language=lang_name,
                        word=word_to_translate,
                    )
                    normalized = self._normalize_translation_result(result)
                    # Save translation to history
                    added = storage.add_translation(
                        lang_code,
                        word_to_translate,
                        normalized["translation"],
                        slow=bool(self.settings.get("tts_slow", False)),
                        reading=normalized["reading"],
                        primary_note=normalized["primary_note"],
                        alternatives=normalized["alternatives"],
                    )
                    self.root.after(
                        0,
                        self._render_translation,
                        word_to_translate,
                        normalized["translation"],
                        lang_code,
                        normalized["reading"],
                        normalized["primary_note"],
                        normalized["alternatives"],
                    )
                    self.root.after(0, self._record_undo_action, added, previous_state, "翻譯")
                    self.root.after(0, self.status_var.set, "✅ 翻譯完成。已存入歷史。")
                except api_client.APIError as e:
                    self.root.after(0, self.status_var.set, f"❌ {e}")
                except Exception as e:
                    self.root.after(0, self.status_var.set, f"❌ 未預期錯誤：{e}")
                finally:
                    self.root.after(
                        0,
                        lambda: self.generate_btn.configure(state="normal" if self.languages else "disabled"),
                    )

            threading.Thread(target=_translate_work, daemon=True).start()
            return

        # Handle scenario split for full lesson generation
        if "/" in scenario:
            parts = scenario.split("/", 1)
            original_scenario = parts[0].strip()
            translation_scenario = parts[1].strip() if len(parts) > 1 else ""
            
            if not original_scenario:
                messagebox.showinfo("提示", "請輸入原始情境（/ 前面的內容）")
                return
            if not translation_scenario:
                messagebox.showinfo("提示", "請輸入翻譯後的情境（/ 後面的內容）")
                return
            # For translation mode, use the original scenario for generation
            scenario = original_scenario

        self.generate_btn.configure(state="disabled")
        self.status_var.set("⏳ 生成中…（首次呼叫模型可能需要 10–30 秒）")
        self._clear_results()

        model = self.settings.get("model", "").strip() or DEFAULT_MODEL

        def _work():
            try:
                payload = api_client.generate_lesson(
                    hf_token=token,
                    model=model,
                    target_language=lang_name,
                    scenario=scenario,
                )
                added = storage.add_batch(lang_code, scenario, payload, slow=bool(self.settings.get("tts_slow", False)))
                self.root.after(0, self._render_results, payload, lang_code)
                self.root.after(0, self._record_undo_action, added, previous_state, "生成")
                self.root.after(0, self.status_var.set, "✅ 完成。已存入歷史。")
            except api_client.APIError as e:
                self.root.after(0, self.status_var.set, f"❌ {e}")
            except Exception as e:
                self.root.after(0, self.status_var.set, f"❌ 未預期錯誤：{e}")
            finally:
                self.root.after(
                    0,
                    lambda: self.generate_btn.configure(state="normal" if self.languages else "disabled"),
                )

        threading.Thread(target=_work, daemon=True).start()

    def _render_results(self, payload: dict, lang_code: str) -> None:
        self.current_payload = payload
        self.current_translation = None
        self.current_lang_code = lang_code
        self._clear_results()
        self._render_section("📖 單字 Words", payload.get("words", []), "word", lang_code)
        self._render_section("📐 文法 Grammar", payload.get("grammar", []), "grammar", lang_code)
        self._render_section("💬 句子 Sentences", payload.get("sentences", []), "sentence", lang_code)

    def _extract_translation_result(self, text: str) -> str:
        """Extract only the translation result from API response."""
        import re
        text = text.strip()
        # Remove common prefixes/patterns that might be included in the response
        patterns_to_remove = [
            r"^[Tt]ranslation[\s:]*",  # "Translation: ..."
            r"^翻譯[\s：:]*",  # "翻譯: ..."
            r"^[Tt]he\s+translation\s+(is|of)?[\s]*",  # "The translation is ..."
            r"^means[\s]*",  # "means ..."
        ]
        for pattern in patterns_to_remove:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
        # Also remove trailing explanations
        text = text.split("(")[0].strip()  # Remove parenthetical explanations
        text = text.split("。")[0].strip()  # Remove after Chinese periods
        text = text.split(".")[0].strip()  # Remove after English periods
        return text

    def _normalize_translation_result(self, result: dict[str, Any]) -> dict[str, Any]:
        translation = self._extract_translation_result(str(result.get("text", "")))
        reading = str(result.get("reading", "")).strip()
        primary_note = str(result.get("primary_note", "")).strip()
        alternatives: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        raw_alternatives = result.get("alternatives", []) or []
        if isinstance(raw_alternatives, list):
            for alternative in raw_alternatives:
                if not isinstance(alternative, dict):
                    continue
                term = self._extract_translation_result(str(alternative.get("term", "")))
                note = str(alternative.get("note", "")).strip()
                if not term:
                    continue
                if term == translation and not primary_note and note:
                    primary_note = note
                    continue
                key = (term, note)
                if key in seen or (term == translation and not note):
                    continue
                seen.add(key)
                alternatives.append({"term": term, "note": note})
        return {
            "translation": translation,
            "reading": reading,
            "primary_note": primary_note,
            "alternatives": alternatives,
        }

    def _translation_title(self, translation: str, reading: str = "") -> str:
        return f"{translation}({reading})" if reading else translation

    def _translation_detail_lines(
        self,
        primary_note: str = "",
        alternatives: list[dict[str, str]] | None = None,
    ) -> list[str]:
        lines: list[str] = []
        if primary_note:
            lines.append(f"常用：{primary_note}")
        for alternative in alternatives or []:
            term = str(alternative.get("term", "")).strip()
            note = str(alternative.get("note", "")).strip()
            if term:
                lines.append(f"{term}：{note or '不同情境用法'}")
        return lines

    def _translation_status_text(
        self,
        translation: str,
        reading: str = "",
        primary_note: str = "",
        alternatives: list[dict[str, str]] | None = None,
    ) -> str:
        lines = [self._translation_title(translation, reading)]
        lines.extend(self._translation_detail_lines(primary_note, alternatives))
        return "\n".join([line for line in lines if line])

    def _translation_summary(
        self,
        translation: str,
        reading: str = "",
        primary_note: str = "",
        alternatives: list[dict[str, str]] | None = None,
    ) -> str:
        parts = [self._translation_title(translation, reading)]
        detail_lines = self._translation_detail_lines(primary_note, alternatives)
        if detail_lines:
            parts.extend(detail_lines)
        return "；".join(parts)

    def _render_translation_card(
        self,
        title: str,
        body: str,
        lang_code: str,
        *,
        note: str = "",
        title_font: tuple[str, ...] = ("Segoe UI", 12),
    ) -> None:
        card_theme = self.theme.card_tokens()
        card = tk.Frame(
            self.results_frame,
            bg=card_theme["bg"],
            highlightbackground=card_theme["border"],
            highlightcolor=card_theme["border"],
            highlightthickness=1,
            bd=0,
            padx=10,
            pady=8,
        )
        card.pack(fill="x", padx=4, pady=3)

        self._render_selectable_text(
            card,
            text=title,
            font=title_font,
            fg=card_theme["title_fg"],
            bg=card_theme["bg"],
            pady=(0, 6),
        )
        self._render_selectable_text(
            card,
            text=body,
            fg=card_theme["body_fg"],
            bg=card_theme["bg"],
            horizontal_drag=True,
        )
        if note:
            self._render_selectable_text(
                card,
                text=note,
                fg=card_theme["body_fg"],
                bg=card_theme["bg"],
                pady=(4, 0),
                horizontal_drag=True,
            )

        btns = ttk.Frame(card)
        btns.configure(style="Surface.TFrame")
        btns.pack(anchor="e", pady=(6, 0))
        ttk.Button(
            btns,
            text="🔊 播放",
            command=lambda t=body, l=lang_code: self._play(t, l),
        ).pack(side="right")

    def _render_translation(
        self,
        word: str,
        translation: str,
        lang_code: str,
        reading: str = "",
        primary_note: str = "",
        alternatives: list[dict[str, str]] | None = None,
    ) -> None:
        """Render a quick translation result."""
        self._clear_results()
        clean_translation = self._extract_translation_result(translation)
        display_translation = self._translation_title(clean_translation, reading)
        tts_text = reading if reading else clean_translation
        self.current_payload = None
        self.current_translation = {
            "word": word,
            "translation": clean_translation,
            "reading": reading,
            "primary_note": primary_note,
            "alternatives": list(alternatives or []),
        }
        self.current_lang_code = lang_code
        self._render_translation_card(
            word,
            display_translation,
            lang_code,
            note=f"常用：{primary_note}" if primary_note else "",
            title_font=("Segoe UI", 14, "bold"),
        )

        for alternative in alternatives or []:
            term = str(alternative.get("term", "")).strip()
            note = str(alternative.get("note", "")).strip()
            if not term:
                continue
            self._render_translation_card(
                f"同義詞：{term}",
                term,
                lang_code,
                note=note,
            )

    def _snapshot_current_state(self) -> dict | None:
        if self.current_payload is not None:
            return {
                "kind": "lesson",
                "payload": copy.deepcopy(self.current_payload),
                "lang_code": self.current_lang_code,
            }
        if self.current_translation is not None:
            return {
                "kind": "translation",
                "word": self.current_translation.get("word", ""),
                "translation": self.current_translation.get("translation", ""),
                "reading": self.current_translation.get("reading", ""),
                "primary_note": self.current_translation.get("primary_note", ""),
                "alternatives": copy.deepcopy(self.current_translation.get("alternatives", [])),
                "lang_code": self.current_lang_code,
            }
        return None

    def _restore_snapshot(self, snapshot: dict | None) -> None:
        if not snapshot:
            self.current_payload = None
            self.current_translation = None
            self.current_lang_code = ""
            self._clear_results()
            return
        if snapshot.get("kind") == "lesson":
            self._render_results(snapshot.get("payload", {}), snapshot.get("lang_code", ""))
            return
        if snapshot.get("kind") == "translation":
            self._render_translation(
                snapshot.get("word", ""),
                snapshot.get("translation", ""),
                snapshot.get("lang_code", ""),
                snapshot.get("reading", ""),
                snapshot.get("primary_note", ""),
                snapshot.get("alternatives", []),
            )
            return
        self.current_payload = None
        self.current_translation = None
        self.current_lang_code = ""
        self._clear_results()

    def _record_undo_action(self, added: dict[str, list[str]], previous_state: dict | None, action_label: str) -> None:
        self.undo_stack.append({
            "added": {category: list(item_ids) for category, item_ids in added.items()},
            "previous_state": previous_state,
            "label": action_label,
        })
        if len(self.undo_stack) > 50:
            self.undo_stack.pop(0)
        self._update_undo_button_state()

    def _update_undo_button_state(self) -> None:
        if self.undo_stack:
            self.undo_btn.configure(state="normal")
        else:
            self.undo_btn.configure(state="disabled")

    def _undo_last_action(self) -> None:
        if not self.undo_stack:
            messagebox.showinfo("提示", "目前沒有可回退的操作。")
            return
        action = self.undo_stack.pop()
        removed_total = 0
        for category, item_ids in action.get("added", {}).items():
            removed_total += storage.delete_items(category, item_ids)
        self._restore_snapshot(action.get("previous_state"))
        self._refresh_history()
        self._update_undo_button_state()
        label = action.get("label", "操作")
        if removed_total > 0:
            self.status_var.set(f"↩ 已回退上一個{label}操作，共移除 {removed_total} 筆歷史。")
        else:
            self.status_var.set(f"↩ 已回退上一個{label}操作。")

    def _render_section(self, title: str, items: list, kind: str, lang_code: str) -> None:
        header = ttk.Label(self.results_frame, text=title, style="SectionTitle.TLabel")
        header.pack(anchor="w", pady=(8, 4), padx=4)
        if not items:
            ttk.Label(self.results_frame, text="（無）", style="Muted.TLabel").pack(anchor="w", padx=12)
            return
        for it in items:
            self._render_card(it, kind, lang_code)

    def _render_card(self, it: dict, kind: str, lang_code: str) -> None:
        card_theme = self.theme.card_tokens()
        card = tk.Frame(
            self.results_frame,
            bg=card_theme["bg"],
            highlightbackground=card_theme["border"],
            highlightcolor=card_theme["border"],
            highlightthickness=1,
            bd=0,
            padx=10,
            pady=8,
        )
        card.pack(fill="x", padx=4, pady=3)

        if kind == "grammar":
            target_text = it.get("point", "")
            sub = it.get("explanation", "")
            example = it.get("example", "")
            tts_text = example or target_text
            self._render_selectable_text(
                card,
                text=target_text,
                font=("Segoe UI", 11, "bold"),
                fg=card_theme["title_fg"],
                bg=card_theme["bg"],
            )
            if sub:
                self._render_selectable_text(
                    card,
                    text=sub,
                    fg=card_theme["body_fg"],
                    bg=card_theme["bg"],
                    horizontal_drag=True,
                )
            if example:
                self._render_selectable_text(
                    card,
                    text=f"例：{example}",
                    fg=card_theme["example_fg"],
                    bg=card_theme["bg"],
                    horizontal_drag=True,
                )
        else:
            target_text = it.get("text", "")
            reading = it.get("reading", "").strip()
            sub = it.get("translation", "")
            tts_text = target_text
            display_text = f"{target_text}({reading})" if reading else target_text
            if kind == "sentence":
                self._render_sentence_with_hover(card, display_text, lang_code, card_theme)
            else:
                self._render_selectable_text(
                    card,
                    text=display_text,
                    font=("Segoe UI", 11, "bold"),
                    fg=card_theme["title_fg"],
                    bg=card_theme["bg"],
                )
            if sub:
                self._render_selectable_text(
                    card,
                    text=sub,
                    fg=card_theme["body_fg"],
                    bg=card_theme["bg"],
                    horizontal_drag=True,
                )

        btns = ttk.Frame(card)
        btns.configure(style="Surface.TFrame")
        btns.pack(anchor="e", pady=(6, 0))
        ttk.Button(btns, text="🔊 播放",
                   command=lambda t=tts_text, l=lang_code: self._play(t, l)).pack(side="right")

    def _lang_name_from_code(self, lang_code: str) -> str:
        """Resolve a TTS language code to the prompt language name."""
        for entry in self.language_entries:
            if entry.get("code") == lang_code:
                return entry.get("name", lang_code)
        return lang_code

    def _tokenize_sentence(self, text: str) -> list[tuple[str, str]]:
        """Split sentence into (display_token, lookup_word) pairs.

        lookup_word is empty for whitespace / punctuation-only tokens.
        For space-separated text, split on whitespace and strip surrounding
        punctuation from each token's lookup form.  For CJK/no-space text,
        tokenise per character (Latin runs kept together).
        """
        import re
        result: list[tuple[str, str]] = []
        if " " in text:
            for tok in re.findall(r"\S+|\s+", text):
                if tok.strip():
                    word = re.sub(
                        r"^[^\w\u3040-\u30ff\u4e00-\u9fff]+|[^\w\u3040-\u30ff\u4e00-\u9fff]+$",
                        "", tok,
                    )
                    result.append((tok, word))
                else:
                    result.append((tok, ""))
        else:
            i = 0
            while i < len(text):
                c = text[i]
                if re.match(r"[a-zA-Z0-9']", c):
                    j = i + 1
                    while j < len(text) and re.match(r"[a-zA-Z0-9']", text[j]):
                        j += 1
                    result.append((text[i:j], text[i:j]))
                    i = j
                elif re.match(r"[\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af]", c):
                    result.append((c, c))
                    i += 1
                else:
                    result.append((c, ""))
                    i += 1
        return result

    def _render_sentence_with_hover(
        self, parent: tk.Widget, sentence_text: str, lang_code: str, card_theme: dict
    ) -> None:
        """Render a sentence as a tk.Text widget with per-word hover tooltips."""
        container = tk.Frame(parent, bg=card_theme["bg"])
        container.pack(anchor="w", fill="x", pady=(0, 2))

        text_widget = tk.Text(
            container,
            font=("Segoe UI", 11, "bold"),
            bg=card_theme["bg"],
            fg=card_theme["title_fg"],
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            wrap="none",
            cursor="xterm",
            height=1,
            padx=0,
            pady=0,
            spacing1=0,
            spacing2=0,
            spacing3=0,
            state="normal",
        )
        text_widget.pack(anchor="w", fill="x")

        scrollbar = ttk.Scrollbar(container, orient="horizontal", command=text_widget.xview)
        scrollbar.pack(fill="x", pady=(2, 0))
        text_widget.configure(xscrollcommand=scrollbar.set)
        self._bind_horizontal_drag(text_widget)

        tokens = self._tokenize_sentence(sentence_text)
        for i, (display, lookup) in enumerate(tokens):
            if lookup:
                tag = f"w{i}"
                text_widget.insert("end", display, (tag,))

                def _enter(e, w=lookup, l=lang_code, tw=text_widget):
                    self._on_word_hover_enter(e, w, l)

                def _leave(e):
                    self._on_word_hover_leave(e)

                text_widget.tag_bind(tag, "<Enter>", _enter)
                text_widget.tag_bind(tag, "<Leave>", _leave)
            else:
                text_widget.insert("end", display)

        text_widget.configure(state="disabled")

        # Auto-adjust height to actual display lines after layout
        _adj = [False]

        def _adjust(e=None):
            if _adj[0]:
                return
            _adj[0] = True
            try:
                count = text_widget.count("1.0", "end-1c", "displaylines")
                h = count[0] if isinstance(count, tuple) else (count or 1)
                text_widget.configure(height=max(1, h))
            except Exception:
                pass
            finally:
                _adj[0] = False

        text_widget.bind("<Configure>", _adjust)

    def _build_selectable_text_widget(
        self,
        parent: tk.Widget,
        text: str,
        *,
        font: tuple[str, ...] = ("Segoe UI", 10),
        fg: str,
        bg: str,
        wrap: str = "word",
    ) -> tk.Text:
        text_widget = tk.Text(
            parent,
            font=font,
            bg=bg,
            fg=fg,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            wrap=wrap,
            cursor="xterm",
            height=1,
            padx=0,
            pady=0,
            spacing1=0,
            spacing2=0,
            spacing3=0,
            state="normal",
        )
        text_widget.insert("1.0", text)
        self._fit_text_height(text_widget)
        text_widget.configure(state="disabled")
        text_widget.bind("<Configure>", lambda _e, tw=text_widget: self._fit_text_height(tw))
        return text_widget

    def _render_selectable_text(
        self,
        parent: tk.Widget,
        text: str,
        *,
        font: tuple[str, ...] = ("Segoe UI", 10),
        fg: str,
        bg: str,
        pady: tuple[int, int] = (0, 2),
        horizontal_drag: bool = False,
    ) -> tk.Text:
        if horizontal_drag:
            container = tk.Frame(parent, bg=bg)
            container.pack(anchor="w", fill="x", pady=pady)
            text_widget = self._build_selectable_text_widget(
                container,
                text,
                font=font,
                fg=fg,
                bg=bg,
                wrap="none",
            )
            text_widget.pack(anchor="w", fill="x")
            scrollbar = ttk.Scrollbar(container, orient="horizontal", command=text_widget.xview)
            scrollbar.pack(fill="x", pady=(2, 0))
            text_widget.configure(xscrollcommand=scrollbar.set)
            self._bind_horizontal_drag(text_widget)
            return text_widget

        text_widget = self._build_selectable_text_widget(
            parent,
            text,
            font=font,
            fg=fg,
            bg=bg,
        )
        text_widget.pack(anchor="w", fill="x", pady=pady)
        return text_widget

    def _fit_text_height(self, text_widget: tk.Text) -> None:
        try:
            count = text_widget.count("1.0", "end-1c", "displaylines")
            height = count[0] if isinstance(count, tuple) else (count or 1)
            text_widget.configure(height=max(1, height))
        except Exception:
            pass

    def _bind_horizontal_drag(self, text_widget: tk.Text) -> None:
        def _start_drag(event: tk.Event) -> str:
            text_widget.scan_mark(event.x, 0)
            return "break"

        def _drag(event: tk.Event) -> str:
            text_widget.scan_dragto(event.x, 0, gain=1)
            return "break"

        def _shift_wheel(event: tk.Event) -> str:
            delta = int(-1 * (event.delta / 120)) if getattr(event, "delta", 0) else 0
            if delta:
                text_widget.xview_scroll(delta, "units")
            return "break"

        text_widget.bind("<ButtonPress-3>", _start_drag)
        text_widget.bind("<B3-Motion>", _drag)
        text_widget.bind("<Shift-MouseWheel>", _shift_wheel)

    # ---- word tooltip helpers ----

    def _on_word_hover_enter(self, event: tk.Event, word: str, lang_code: str) -> None:
        if self._word_tooltip_after_id is not None:
            self.root.after_cancel(self._word_tooltip_after_id)
            self._word_tooltip_after_id = None
        self._hide_word_tooltip()
        self._show_word_tooltip(event.x_root, event.y_root, word, lang_code)

    def _on_word_hover_leave(self, event: tk.Event) -> None:
        self._word_tooltip_after_id = self.root.after(300, self._maybe_hide_word_tooltip)

    def _cancel_tooltip_hide(self) -> None:
        if self._word_tooltip_after_id is not None:
            self.root.after_cancel(self._word_tooltip_after_id)
            self._word_tooltip_after_id = None

    def _maybe_hide_word_tooltip(self) -> None:
        self._word_tooltip_after_id = None
        win = self._word_tooltip_win
        if not win:
            return
        try:
            px, py = win.winfo_pointerxy()
            wx, wy = win.winfo_rootx(), win.winfo_rooty()
            ww, wh = win.winfo_width(), win.winfo_height()
            if wx <= px <= wx + ww and wy <= py <= wy + wh:
                return  # mouse is still inside tooltip
        except Exception:
            pass
        self._hide_word_tooltip()

    def _hide_word_tooltip(self) -> None:
        win = self._word_tooltip_win
        if win:
            self._word_tooltip_win = None
            try:
                win.destroy()
            except Exception:
                pass

    def _show_word_tooltip(self, x: int, y: int, word: str, lang_code: str) -> None:
        """Create and display a floating word-lookup tooltip near the cursor."""
        card_theme = self.theme.card_tokens()
        win = tk.Toplevel(self.root)
        win.withdraw()
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        self._word_tooltip_win = win

        outer = tk.Frame(win, bg=card_theme["border"], padx=1, pady=1)
        outer.pack(fill="both", expand=True)
        inner = tk.Frame(outer, bg=card_theme["bg"], padx=10, pady=8)
        inner.pack(fill="both", expand=True)

        tk.Label(
            inner, text=word,
            font=("Segoe UI", 13, "bold"),
            bg=card_theme["bg"], fg=card_theme["title_fg"],
        ).pack(anchor="w")

        status_var = tk.StringVar(value="⏳ 查詢中…")
        tk.Label(
            inner, textvariable=status_var,
            font=("Segoe UI", 10),
            bg=card_theme["bg"], fg=card_theme["body_fg"],
            wraplength=280, justify="left",
        ).pack(anchor="w", pady=(4, 0))

        btn_frame = tk.Frame(inner, bg=card_theme["bg"])
        btn_frame.pack(anchor="e", pady=(8, 0))

        save_btn = ttk.Button(btn_frame, text="📌 加入歷史", state="disabled")
        save_btn.pack(side="right")

        win.bind("<Enter>", lambda _e: self._cancel_tooltip_hide())
        win.bind("<Leave>", lambda e: self._on_word_hover_leave(e))

        # Position near cursor but stay on screen
        win.update_idletasks()
        tw = win.winfo_reqwidth()
        th = win.winfo_reqheight()
        tx, ty = x + 14, y + 22
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        if tx + tw > sw:
            tx = x - tw - 14
        if ty + th > sh:
            ty = y - th - 10
        win.geometry(f"+{tx}+{ty}")
        win.deiconify()

        # --- nested helpers for async fetch ---

        def _save_word(
            translation: str,
            reading: str,
            primary_note: str,
            alternatives: list[dict[str, str]],
        ) -> None:
            slow = bool(self.settings.get("tts_slow", False))
            storage.add_translation(
                lang_code,
                word,
                translation,
                slow=slow,
                reading=reading,
                primary_note=primary_note,
                alternatives=alternatives,
            )
            self._refresh_history()
            try:
                if win.winfo_exists():
                    save_btn.configure(state="disabled", text="✅ 已加入")
            except Exception:
                pass

        def _on_result(
            status_text: str,
            clean: str,
            reading: str,
            primary_note: str,
            alternatives: list[dict[str, str]],
        ) -> None:
            try:
                if win.winfo_exists():
                    status_var.set(status_text)
                    save_btn.configure(
                        state="normal",
                        command=lambda t=clean, r=reading, p=primary_note, a=alternatives: _save_word(t, r, p, a),
                    )
            except Exception:
                pass

        def _on_error(msg: str) -> None:
            try:
                if win.winfo_exists():
                    status_var.set(f"❌ {msg[:80]}")
            except Exception:
                pass

        cached_value = self._lookup_word_translation_cache(word, lang_code)
        if cached_value is not None:
            _on_result(
                self._translation_status_text(
                    cached_value.get("translation", ""),
                    cached_value.get("reading", ""),
                    cached_value.get("primary_note", ""),
                    cached_value.get("alternatives", []),
                ),
                cached_value.get("translation", ""),
                cached_value.get("reading", ""),
                cached_value.get("primary_note", ""),
                list(cached_value.get("alternatives", [])),
            )
            return

        token = self.settings.get("hf_token", "").strip()
        if not token:
            status_var.set("請先設定 Hugging Face Token")
            return

        model = self.settings.get("model", "").strip() or DEFAULT_MODEL

        def _fetch() -> None:
            try:
                result = api_client.translate_word(
                    hf_token=token,
                    model=model,
                    target_language="Traditional Chinese",
                    word=word,
                )
                normalized = self._normalize_translation_result(result)
                self._store_word_translation_cache(
                    word,
                    lang_code,
                    normalized["translation"],
                    normalized["reading"],
                    normalized["primary_note"],
                    normalized["alternatives"],
                )
                self.root.after(
                    0,
                    lambda: _on_result(
                        self._translation_status_text(
                            normalized["translation"],
                            normalized["reading"],
                            normalized["primary_note"],
                            normalized["alternatives"],
                        ),
                        normalized["translation"],
                        normalized["reading"],
                        normalized["primary_note"],
                        normalized["alternatives"],
                    ),
                )
            except Exception as exc:
                self.root.after(0, lambda: _on_error(str(exc)))

        threading.Thread(target=_fetch, daemon=True).start()

    def _play(self, text: str, lang_code: str) -> None:
        if not text.strip():
            return
        slow = bool(self.settings.get("tts_slow", False))
        tts.play_async(
            text, lang_code, slow=slow,
            on_error=lambda e: self.root.after(
                0, lambda: messagebox.showerror("播放失敗", str(e))
            ),
        )

    # ---------- history tab ----------
    def _build_history_tab(self) -> None:
        sub = ttk.Notebook(self.history_tab)
        sub.pack(fill="both", expand=True, padx=PAD, pady=PAD)
        self.history_sub = sub

        self.history_views: dict[str, dict] = {}
        for key, label, cols in [
            ("words",     "📖 單字",
                         [("ts", "時間", 130), ("lang", "語言", 60),
                            ("translation", "翻譯", 260)]),
            ("grammar",   "📐 文法",
             [("ts", "時間", 130), ("lang", "語言", 60),
                            ("explanation", "說明", 260),
              ("example", "例句", 220)]),
            ("sentences", "💬 句子",
             [("ts", "時間", 130), ("lang", "語言", 60),
                            ("translation", "翻譯", 300)]),
            ("translations", "🔤 翻譯",
             [("ts", "時間", 130), ("lang", "語言", 60),
                            ("translation", "翻譯結果", 300)]),
        ]:
            frame = ttk.Frame(sub, style="Surface.TFrame")
            sub.add(frame, text=label)

            action_bar = ttk.Frame(frame, style="Surface.TFrame")
            action_bar.pack(fill="x", padx=4, pady=(4, 8))
            play_selected_btn = ttk.Button(
                action_bar,
                text="🔊 播放所選條目",
                command=lambda k=key: self._history_play(k),
                state="disabled",
            )
            play_selected_btn.pack(side="left")
            action_hint = ttk.Label(
                action_bar,
                text="選擇條目後即可播放本地語音",
                style="Muted.TLabel",
            )
            action_hint.pack(side="left", padx=(10, 0))

            tree_holder = ttk.Frame(frame, style="Surface.TFrame")
            tree_holder.pack(fill="both", expand=True)

            tv = ttk.Treeview(tree_holder, columns=[c[0] for c in cols], show="tree headings")
            tv.heading("#0", text="語境 / 內容")
            tv.column("#0", width=280, anchor="w")
            for cid, ctitle, cw in cols:
                tv.heading(cid, text=ctitle)
                tv.column(cid, width=cw, anchor="w")
            vsb = ttk.Scrollbar(tree_holder, orient="vertical", command=tv.yview)
            # horizontal scrollbar intentionally omitted to avoid visual clutter;
            # users can pan horizontally via right-drag or Shift+MouseWheel
            tv.configure(yscrollcommand=vsb.set)
            tv.pack(side="left", fill="both", expand=True)
            vsb.pack(side="right", fill="y")
            # xsb intentionally not packed
            # double-click to delete
            tv.bind("<Double-1>", lambda e, k=key: self._history_delete(k))
            tv.bind("<<TreeviewSelect>>", lambda _e, k=key: self._on_history_select(k))
            tv.bind("<Shift-MouseWheel>", self._on_history_shift_mousewheel)

            grammar_preview = None
            grammar_preview_body = None
            translation_preview = None
            translation_preview_body = None
            if key == "grammar":
                grammar_preview = ttk.Frame(frame, style="Surface.TFrame")
                grammar_preview.pack(fill="x", padx=4, pady=(8, 0))
                ttk.Label(grammar_preview, text="例句預覽", style="SectionTitle.TLabel").pack(anchor="w")
                grammar_preview_body = ttk.Frame(grammar_preview, style="Surface.TFrame")
                grammar_preview_body.pack(fill="x", pady=(6, 0))
                ttk.Label(
                    grammar_preview_body,
                    text="選取一筆文法歷史後，這裡會顯示可逐字懸停查詢的例句。",
                    style="Muted.TLabel",
                    justify="left",
                ).pack(anchor="w")
            elif key == "translations":
                translation_preview = ttk.Frame(frame, style="Surface.TFrame")
                translation_preview.pack(fill="x", padx=4, pady=(8, 0))
                ttk.Label(translation_preview, text="翻譯預覽", style="SectionTitle.TLabel").pack(anchor="w")
                translation_preview_body = ttk.Frame(translation_preview, style="Surface.TFrame")
                translation_preview_body.pack(fill="x", pady=(6, 0))
                ttk.Label(
                    translation_preview_body,
                    text="選取一筆翻譯歷史後，這裡會顯示完整翻譯內容。",
                    style="Muted.TLabel",
                    justify="left",
                ).pack(anchor="w")

            btn_bar = ttk.Frame(self.history_tab)
            ttk.Button(btn_bar, text="🔊 播放",
                       command=lambda k=key: self._history_play(k)).pack(side="left", padx=2)
            ttk.Button(btn_bar, text="🗑 刪除 (或雙擊)",
                       command=lambda k=key: self._history_delete(k)).pack(side="left", padx=2)
            ttk.Button(btn_bar, text="🗑🗑 清空本頁",
                       command=lambda k=key: self._history_clear_tab(k)).pack(side="left", padx=2)
            ttk.Button(btn_bar, text="📤 匯出 JSON",
                       command=self._history_export).pack(side="left", padx=2)
            ttk.Button(btn_bar, text="🔄 重新整理",
                       command=self._refresh_history).pack(side="left", padx=2)

            self.history_views[key] = {
                "tv": tv,
                "btn_bar": btn_bar,
                "frame": frame,
                "play_btn": play_selected_btn,
                "action_hint": action_hint,
                "grammar_preview": grammar_preview,
                "grammar_preview_body": grammar_preview_body,
                "translation_preview": translation_preview,
                "translation_preview_body": translation_preview_body,
                "item_lookup": {},
                "scenario_lookup": {},
                "scenario_id_lookup": {},
            }

        # Show button bar matching active sub-tab
        self.history_btn_holder = ttk.Frame(self.history_tab)
        self.history_btn_holder.pack(fill="x", padx=PAD, pady=(0, PAD))
        sub.bind("<<NotebookTabChanged>>", lambda _e: self._sync_history_btn_bar())
        self._sync_history_btn_bar()

    def _sync_history_btn_bar(self) -> None:
        for w in self.history_btn_holder.winfo_children():
            w.pack_forget()
        idx = self.history_sub.index(self.history_sub.select())
        key = ["words", "grammar", "sentences", "translations"][idx]
        self.history_views[key]["btn_bar"].pack(in_=self.history_btn_holder, side="left")

    def _on_history_shift_mousewheel(self, event) -> str:
        widget = event.widget
        delta = int(-1 * (event.delta / 120)) if getattr(event, "delta", 0) else 0
        if delta:
            widget.xview_scroll(delta, "units")
        return "break"

    def _refresh_history(self) -> None:
        history = storage.load_history()
        for key, view in self.history_views.items():
            tv: ttk.Treeview = view["tv"]
            view["item_lookup"] = {}
            view["scenario_lookup"] = {}
            view["scenario_id_lookup"] = {}
            tv.delete(*tv.get_children())
            items = sorted(history.get(key, []), key=lambda x: x.get("ts", 0), reverse=True)
            for it in items:
                # 翻譯（translations）不使用語境（scenario）摺疊群組，直接列在根目錄
                view["item_lookup"][it.get("id")] = it
                if key == "translations":
                    raw_translation = it.get("translation", "")
                    reading = (it.get("reading") or "").strip()
                    display_tr = self._translation_summary(
                        raw_translation,
                        reading,
                        str(it.get("primary_note", "")).strip(),
                        it.get("alternatives", []),
                    )
                    vals = (_fmt_ts(it.get("ts", 0)), it.get("lang", ""), display_tr)
                    text = it.get("word", "")
                    tv.insert("", "end", iid=it.get("id"), text=text, values=vals)
                    continue

                scenario = it.get("scenario", "未分類") or "未分類"
                scenario_id = view["scenario_lookup"].get(scenario)
                if not scenario_id:
                    scenario_id = f"scenario::{hash((key, scenario))}"
                    latest_ts = _fmt_ts(it.get("ts", 0))
                    tv.insert(
                        "",
                        "end",
                        iid=scenario_id,
                        text=scenario,
                        values=(latest_ts, it.get("lang", ""), *([""] * (len(tv["columns"]) - 2))),
                        open=False,
                    )
                    view["scenario_lookup"][scenario] = scenario_id
                    view["scenario_id_lookup"][scenario_id] = scenario

                if key == "words":
                    vals = (_fmt_ts(it.get("ts", 0)), it.get("lang", ""), it.get("translation", ""))
                    raw_text = it.get("text", "")
                    reading = (it.get("reading") or "").strip()
                    text = f"{raw_text}({reading})" if reading else raw_text
                elif key == "grammar":
                    vals = (_fmt_ts(it.get("ts", 0)), it.get("lang", ""), it.get("explanation", ""), it.get("example", ""))
                    text = it.get("point", "")
                else:
                    vals = (_fmt_ts(it.get("ts", 0)), it.get("lang", ""), it.get("translation", ""))
                    text = it.get("text", "")
                tv.insert(scenario_id, "end", iid=it.get("id"), text=text, values=vals)
            self._update_history_action_state(key)

    def _selected_item(self, key: str):
        tv: ttk.Treeview = self.history_views[key]["tv"]
        sel = tv.selection()
        if not sel:
            return None, None
        item_id = sel[0]
        if str(item_id).startswith("scenario::"):
            return item_id, None
        item_lookup: dict = self.history_views[key].get("item_lookup", {})
        if item_id in item_lookup:
            return item_id, item_lookup[item_id]
        history = storage.load_history()
        for it in history.get(key, []):
            if it.get("id") == item_id:
                self.history_views[key].setdefault("item_lookup", {})[item_id] = it
                return item_id, it
        return item_id, None

    def _history_play(self, key: str) -> None:
        _id, it = self._selected_item(key)
        if not it:
            messagebox.showinfo("提示", "請先展開語境並選一筆條目")
            return
        if key == "translations":
            lang = it.get("lang", "en")
            reading = (it.get("reading") or "").strip()
            translation = (it.get("translation") or "").strip()
            # Play hiragana reading if available, otherwise play translation text
            text = reading if reading else translation
            if not text:
                text = (it.get("word") or "").strip()
            self._play(text, lang)
            return
        audio_ref = it.get("playback_audio")
        if isinstance(audio_ref, dict) and audio_ref.get("hash"):
            tts.play_audio_ref_async(
                audio_ref,
                on_error=lambda e: self.root.after(
                    0, lambda: messagebox.showerror("播放失敗", str(e))
                ),
            )
            return
        text = it.get("example") if key == "grammar" and it.get("example") else \
            it.get("text") or it.get("point") or ""
        lang = it.get("lang", "en")
        self._play(text, lang)

    def _history_delete(self, key: str) -> None:
        item_id, it = self._selected_item(key)
        if item_id and str(item_id).startswith("scenario::"):
            scenario = self.history_views[key].get("scenario_id_lookup", {}).get(item_id)
            if not scenario:
                messagebox.showinfo("提示", "找不到這個語境群組。請重新整理後再試。")
                return
            count = len(self.history_views[key]["tv"].get_children(item_id))
            if count == 0:
                messagebox.showinfo("提示", "這個語境群組目前沒有子項。")
                return
            if messagebox.askyesno("確認", f"確定刪除語境『{scenario}』以及底下 {count} 筆子項？"):
                storage.delete_scenario(key, scenario)
                self._refresh_history()
            return
        if not it:
            messagebox.showinfo("提示", "請先展開語境並選一筆條目")
            return
        if messagebox.askyesno("確認", "確定刪除這筆紀錄？"):
            storage.delete_item(key, item_id)
            self._refresh_history()

    def _history_clear_tab(self, key: str) -> None:
        label = {"words": "單字", "grammar": "文法", "sentences": "句子"}.get(key, key)
        count = len(storage.load_history().get(key, []))
        if count == 0:
            messagebox.showinfo("提示", f"『{label}』歷史已經是空的。")
            return
        if messagebox.askyesno("確認清空", f"確定清空所有『{label}』歷史（共 {count} 筆）？\n此動作無法復原。"):
            storage.clear_history_category(key)
            self._refresh_history()

    def _on_history_select(self, key: str) -> None:
        self._update_history_action_state(key)

    def _set_history_grammar_preview(self, item: dict | None) -> None:
        view = self.history_views.get("grammar", {})
        body = view.get("grammar_preview_body")
        if body is None:
            return
        for child in body.winfo_children():
            child.destroy()

        if not item:
            ttk.Label(
                body,
                text="選取一筆文法歷史後，這裡會顯示可逐字懸停查詢的例句。",
                style="Muted.TLabel",
                justify="left",
            ).pack(anchor="w")
            return

        card_theme = self.theme.card_tokens()
        card = tk.Frame(
            body,
            bg=card_theme["bg"],
            highlightbackground=card_theme["border"],
            highlightcolor=card_theme["border"],
            highlightthickness=1,
            bd=0,
            padx=10,
            pady=8,
        )
        card.pack(fill="x")

        point = (item.get("point") or "").strip()
        explanation = (item.get("explanation") or "").strip()
        example = (item.get("example") or "").strip()
        lang_code = (item.get("lang") or "").strip()

        if point:
            self._render_selectable_text(
                card,
                text=point,
                font=("Segoe UI", 11, "bold"),
                fg=card_theme["title_fg"],
                bg=card_theme["bg"],
            )
        if explanation:
            self._render_selectable_text(
                card,
                text=explanation,
                fg=card_theme["body_fg"],
                bg=card_theme["bg"],
                pady=(4, 0),
                horizontal_drag=True,
            )
        if example:
            self._render_selectable_text(
                card,
                text="例：",
                fg=card_theme["example_fg"],
                bg=card_theme["bg"],
                pady=(6, 0),
            )
            self._render_sentence_with_hover(card, example, lang_code, card_theme)
        else:
            ttk.Label(card, text="這筆文法沒有例句。", style="Muted.TLabel").pack(anchor="w", pady=(6, 0))

    def _set_history_translation_preview(self, item: dict | None) -> None:
        view = self.history_views.get("translations", {})
        body = view.get("translation_preview_body")
        if body is None:
            return
        for child in body.winfo_children():
            child.destroy()

        if not item:
            ttk.Label(
                body,
                text="選取一筆翻譯歷史後，這裡會顯示完整翻譯內容。",
                style="Muted.TLabel",
                justify="left",
            ).pack(anchor="w")
            return

        card_theme = self.theme.card_tokens()
        card = tk.Frame(
            body,
            bg=card_theme["bg"],
            highlightbackground=card_theme["border"],
            highlightcolor=card_theme["border"],
            highlightthickness=1,
            bd=0,
            padx=10,
            pady=8,
        )
        card.pack(fill="x")

        word = (item.get("word") or "").strip()
        translation = (item.get("translation") or "").strip()
        reading = (item.get("reading") or "").strip()
        primary_note = str(item.get("primary_note", "")).strip()
        alternatives = item.get("alternatives", [])

        if word:
            self._render_selectable_text(
                card,
                text=word,
                font=("Segoe UI", 11, "bold"),
                fg=card_theme["title_fg"],
                bg=card_theme["bg"],
            )

        full_translation = self._translation_status_text(
            translation,
            reading,
            primary_note,
            alternatives,
        )
        if full_translation:
            self._render_selectable_text(
                card,
                text=full_translation,
                fg=card_theme["body_fg"],
                bg=card_theme["bg"],
                pady=(4, 0),
                horizontal_drag=True,
            )

    def _update_history_action_state(self, key: str) -> None:
        view = self.history_views[key]
        item_id, item = self._selected_item(key)
        play_btn: ttk.Button = view["play_btn"]
        action_hint: ttk.Label = view["action_hint"]
        if key == "grammar":
            self._set_history_grammar_preview(item)
        elif key == "translations":
            self._set_history_translation_preview(item)
        if item:
            play_btn.configure(state="normal")
            label = item.get("text") or item.get("point") or "這筆內容"
            action_hint.configure(text=f"已選取：{label}")
            return
        play_btn.configure(state="disabled")
        if item_id and str(item_id).startswith("scenario::"):
            action_hint.configure(text="目前選到語境群組，請再選一筆實際條目")
        else:
            action_hint.configure(text="選擇條目後即可播放本地語音")

    def _history_export(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialfile="tiny_lesson_history.json",
        )
        if not path:
            return
        import json
        with open(path, "w", encoding="utf-8") as f:
            json.dump(storage.load_history(), f, ensure_ascii=False, indent=2)
        messagebox.showinfo("匯出完成", f"已匯出至：\n{path}")

    # ---------- settings tab ----------
    def _build_settings_tab(self) -> None:
        f = ttk.Frame(self.settings_tab, padding=PAD * 2)
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="Hugging Face API Token：").grid(row=0, column=0, sticky="w", pady=4)
        self.token_var = tk.StringVar(value=self.settings.get("hf_token", ""))
        self.token_entry = ttk.Entry(f, textvariable=self.token_var, width=60, show="•")
        self.token_entry.grid(row=0, column=1, sticky="ew", pady=4)
        self.show_token_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            f, text="顯示", variable=self.show_token_var,
            command=lambda: self.token_entry.configure(
                show="" if self.show_token_var.get() else "•"
            ),
        ).grid(row=0, column=2, padx=PAD)

        ttk.Label(f, text="模型名稱：").grid(row=1, column=0, sticky="w", pady=4)
        current_model = self.settings.get("model", "") or DEFAULT_MODEL
        self.model_var = tk.StringVar(value=current_model)
        model_values = list(AVAILABLE_MODELS)
        if current_model not in model_values:
            model_values.insert(0, current_model)
        self.model_combo = ttk.Combobox(
            f, textvariable=self.model_var, values=model_values, width=58,
        )
        self.model_combo.grid(row=1, column=1, sticky="ew", pady=4)

        ttk.Label(f, text="介面主題：").grid(row=2, column=0, sticky="w", pady=4)
        current_theme = self.settings.get("theme", DEFAULT_THEME)
        self.theme_var = tk.StringVar(value=THEME_LABEL_BY_NAME.get(current_theme, THEME_OPTIONS[0][0]))
        self.theme_combo = ttk.Combobox(
            f,
            textvariable=self.theme_var,
            values=[label for label, _name in THEME_OPTIONS],
            state="readonly",
            width=58,
        )
        self.theme_combo.grid(row=2, column=1, sticky="ew", pady=4)

        ttk.Label(f, text="可用語言：").grid(row=3, column=0, sticky="nw", pady=4)
        language_panel = ttk.Frame(f)
        language_panel.grid(row=3, column=1, columnspan=2, sticky="nsew", pady=4)
        self.language_tree = ttk.Treeview(
            language_panel,
            columns=("code", "name"),
            show="headings",
            height=5,
            selectmode="browse",
        )
        self.language_tree.heading("code", text="TTS 代碼")
        self.language_tree.heading("name", text="Prompt 名稱")
        self.language_tree.column("code", width=100, anchor="w")
        self.language_tree.column("name", width=180, anchor="w")
        self.language_tree.pack(side="left", fill="both", expand=True)
        language_scroll = ttk.Scrollbar(language_panel, orient="vertical", command=self.language_tree.yview)
        language_scroll.pack(side="right", fill="y")
        self.language_tree.configure(yscrollcommand=language_scroll.set)

        self.language_hint_var = tk.StringVar(value="可新增或刪除語言。若清單為空，學習頁會停用生成。")
        ttk.Label(f, textvariable=self.language_hint_var, style="Muted.TLabel").grid(
            row=4, column=1, columnspan=2, sticky="w", pady=(0, 6)
        )

        self.new_language_display_var = tk.StringVar()
        self.new_language_code_var = tk.StringVar()
        self.new_language_name_var = tk.StringVar()
        language_form = ttk.Frame(f)
        language_form.grid(row=5, column=1, columnspan=2, sticky="ew", pady=4)
        ttk.Label(language_form, text="顯示名稱").grid(row=0, column=0, sticky="w")
        ttk.Entry(language_form, textvariable=self.new_language_display_var, width=28).grid(row=1, column=0, sticky="ew", padx=(0, 6))
        ttk.Label(language_form, text="TTS 代碼").grid(row=0, column=1, sticky="w")
        ttk.Entry(language_form, textvariable=self.new_language_code_var, width=14).grid(row=1, column=1, sticky="ew", padx=(0, 6))
        ttk.Label(language_form, text="Prompt 名稱").grid(row=0, column=2, sticky="w")
        ttk.Entry(language_form, textvariable=self.new_language_name_var, width=20).grid(row=1, column=2, sticky="ew")
        language_form.columnconfigure(0, weight=2)
        language_form.columnconfigure(1, weight=1)
        language_form.columnconfigure(2, weight=1)

        language_actions = ttk.Frame(f)
        language_actions.grid(row=6, column=1, columnspan=2, sticky="w", pady=(2, 8))
        ttk.Button(language_actions, text="➕ 新增語言", command=self._add_language).pack(side="left", padx=(0, 6))
        ttk.Button(language_actions, text="➖ 刪除所選語言", command=self._remove_selected_language).pack(side="left")

        self.slow_var = tk.BooleanVar(value=bool(self.settings.get("tts_slow", False)))
        ttk.Checkbutton(f, text="TTS 慢速朗讀", variable=self.slow_var).grid(
            row=7, column=1, sticky="w", pady=4
        )

        btns = ttk.Frame(f)
        btns.grid(row=8, column=0, columnspan=3, sticky="w", pady=(PAD * 2, 0))
        ttk.Button(btns, text="💾 儲存設定", command=self._save_settings, style="Accent.TButton").pack(side="left", padx=4)
        ttk.Button(btns, text="🧹 清除全部歷史", command=self._clear_history).pack(side="left", padx=4)

        info = (
            "說明：\n"
            "1. 到 https://huggingface.co/settings/tokens 申請免費 Token (Read 權限即可)。\n"
            "2. 模型預設使用 mistralai/Mistral-7B-Instruct-v0.3，可改成其他 Inference 支援的模型。\n"
            "3. 首次呼叫模型若回 503 表示冷啟動，本程式會自動重試。\n"
            "4. TTS 使用 gTTS（需網路）。\n"
            "5. 自訂語言時，請填入正確的 gTTS 語言代碼與用於提示詞的英文語言名稱。"
        )
        ttk.Label(f, text=info, style="Info.TLabel", justify="left").grid(
            row=9, column=0, columnspan=3, sticky="w", pady=(PAD * 2, 0)
        )

        f.columnconfigure(1, weight=1)
        self._refresh_language_list()

    def _save_settings(self) -> None:
        theme_name = THEME_NAME_BY_LABEL.get(self.theme_var.get(), DEFAULT_THEME)
        languages = storage.normalize_languages(self.language_entries)
        self.settings = {
            "hf_token": self.token_var.get().strip(),
            "model": self.model_var.get().strip(),
            "tts_slow": bool(self.slow_var.get()),
            "theme": theme_name,
            "languages": languages,
        }
        storage.save_settings(self.settings)
        self.language_entries = languages
        self.languages = storage.get_language_map(self.settings)
        self._refresh_language_list()
        self._refresh_language_selector()
        self._apply_theme(theme_name)
        if not self.languages:
            messagebox.showwarning("已儲存", "設定已儲存，但目前沒有任何可用語言。請新增至少一種語言後再生成內容。")
            return
        messagebox.showinfo("已儲存", "設定已儲存。")

    def _clear_history(self) -> None:
        if messagebox.askyesno("確認", "確定要清除所有學習歷史？此動作無法復原。"):
            storage.clear_history()
            self._clear_word_translation_cache()
            self.undo_stack.clear()
            self._update_undo_button_state()
            self._refresh_history()
            messagebox.showinfo("已清除", "歷史與查字快取已清空。")

    def _refresh_language_selector(self, show_status: bool = True) -> None:
        self.languages = storage.get_language_map({"languages": self.language_entries})
        values = list(self.languages.keys())
        self.lang_combo.configure(values=values)
        if values:
            current = self.lang_var.get()
            if current not in self.languages:
                self.lang_var.set(values[0])
            self.lang_combo.configure(state="readonly")
            self.generate_btn.configure(state="normal")
            if show_status and self.status_var.get().startswith("⚠ 目前沒有可用語言"):
                self.status_var.set("輸入情境後按『生成』。例如：在咖啡店點一杯拿鐵。")
        else:
            self.lang_var.set("")
            self.lang_combo.configure(state="disabled")
            self.generate_btn.configure(state="disabled")
            if show_status:
                self.status_var.set("⚠ 目前沒有可用語言，請到『設定』新增至少一種語言。")

    def _refresh_language_list(self) -> None:
        self.language_tree.delete(*self.language_tree.get_children())
        for entry in self.language_entries:
            self.language_tree.insert(
                "",
                "end",
                iid=entry["display"],
                text=entry["display"],
                values=(entry["code"], entry["name"]),
            )
        if self.language_entries:
            self.language_hint_var.set("可新增或刪除語言。若清單為空，學習頁會停用生成。")
        else:
            self.language_hint_var.set("目前沒有任何語言。請新增至少一種語言，否則無法生成內容。")

    def _add_language(self) -> None:
        display = self.new_language_display_var.get().strip()
        code = self.new_language_code_var.get().strip()
        name = self.new_language_name_var.get().strip()
        if not display or not code or not name:
            messagebox.showwarning("欄位不足", "請完整填入顯示名稱、TTS 代碼與 Prompt 名稱。")
            return
        if any(entry["display"] == display for entry in self.language_entries):
            messagebox.showwarning("名稱重複", "顯示名稱已存在，請改用其他名稱。")
            return
        try:
            canonical_code = tts.normalize_language_code(code)
        except RuntimeError as e:
            messagebox.showwarning("TTS 代碼不支援", str(e))
            return
        self.language_entries.append({"display": display, "code": canonical_code, "name": name})
        self._refresh_language_list()
        self._refresh_language_selector(show_status=False)
        self.new_language_display_var.set("")
        self.new_language_code_var.set("")
        self.new_language_name_var.set("")

    def _remove_selected_language(self) -> None:
        selection = self.language_tree.selection()
        if not selection:
            messagebox.showinfo("提示", "請先在語言清單選一筆要刪除的語言。")
            return
        display = selection[0]
        self.language_entries = [entry for entry in self.language_entries if entry["display"] != display]
        self._refresh_language_list()
        self._refresh_language_selector()

    # ---------- events ----------
    def _on_tab_changed(self, _event) -> None:
        if self.notebook.index(self.notebook.select()) == 1:
            self._refresh_history()

    def _apply_theme(self, theme_name: str | None = None) -> None:
        if theme_name is not None:
            self.theme.set_theme(theme_name)
        else:
            self.theme.apply_theme()
        self.theme.apply_canvas(self.canvas)
        self.results_frame.configure(style="Surface.TFrame")
        self._refresh_history()
        self._restore_snapshot(self._snapshot_current_state())

    def _load_word_translation_cache(self) -> None:
        try:
            with open(WORD_LOOKUP_CACHE_FILE, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return

        if not isinstance(payload, dict):
            return

        cache: dict[tuple[str, str], dict[str, Any]] = {}
        for lang_code, items in payload.items():
            if not isinstance(lang_code, str) or not isinstance(items, dict):
                continue
            for word, value in items.items():
                if not isinstance(word, str) or not isinstance(value, dict):
                    continue
                translation = str(value.get("translation", "")).strip()
                reading = str(value.get("reading", "")).strip()
                primary_note = str(value.get("primary_note", "")).strip()
                alternatives: list[dict[str, str]] = []
                raw_alternatives = value.get("alternatives", []) or []
                if isinstance(raw_alternatives, list):
                    for alternative in raw_alternatives:
                        if not isinstance(alternative, dict):
                            continue
                        term = str(alternative.get("term", "")).strip()
                        note = str(alternative.get("note", "")).strip()
                        if term:
                            alternatives.append({"term": term, "note": note})
                if translation:
                    cache[(word, lang_code)] = {
                        "translation": translation,
                        "reading": reading,
                        "primary_note": primary_note,
                        "alternatives": alternatives,
                    }

        self._word_translation_cache = cache

    def _persist_word_translation_cache(self) -> None:
        payload: dict[str, dict[str, dict[str, str]]] = {}
        for (word, lang_code), value in self._word_translation_cache.items():
            payload.setdefault(lang_code, {})[word] = {
                "translation": str(value.get("translation", "")).strip(),
                "reading": str(value.get("reading", "")).strip(),
                "primary_note": str(value.get("primary_note", "")).strip(),
                "alternatives": list(value.get("alternatives", [])),
            }

        tmp_path = WORD_LOOKUP_CACHE_FILE.with_suffix(WORD_LOOKUP_CACHE_FILE.suffix + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        tmp_path.replace(WORD_LOOKUP_CACHE_FILE)

    def _store_word_translation_cache(
        self,
        word: str,
        lang_code: str,
        translation: str,
        reading: str,
        primary_note: str,
        alternatives: list[dict[str, str]],
    ) -> None:
        with self._word_cache_lock:
            self._word_translation_cache[(word, lang_code)] = {
                "translation": translation,
                "reading": reading,
                "primary_note": primary_note,
                "alternatives": list(alternatives),
            }
            self._persist_word_translation_cache()

    def _lookup_word_translation_cache(self, word: str, lang_code: str) -> dict[str, Any] | None:
        with self._word_cache_lock:
            return self._word_translation_cache.get((word, lang_code))

    def _clear_word_translation_cache(self) -> None:
        with self._word_cache_lock:
            self._word_translation_cache.clear()
        try:
            WORD_LOOKUP_CACHE_FILE.unlink(missing_ok=True)
        except OSError:
            pass

    def _on_close(self) -> None:
        self._cancel_tooltip_hide()
        self._hide_word_tooltip()
        self.root.destroy()


def run() -> None:
    root = tk.Tk()
    TinyLessonApp(root)
    root.mainloop()
