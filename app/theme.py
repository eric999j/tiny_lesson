"""Theme tokens and style application for Tiny Lesson."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk


PAD = 8
WINDOW_GEOMETRY = "900x680"
DEFAULT_THEME = "light"

THEME_OPTIONS: list[tuple[str, str]] = [
    ("淺色 Light", "light"),
    ("深色 Dark", "dark"),
]
THEME_LABEL_BY_NAME = {name: label for label, name in THEME_OPTIONS}
THEME_NAME_BY_LABEL = {label: name for label, name in THEME_OPTIONS}

THEMES: dict[str, dict[str, str]] = {
    "light": {
        "app_bg": "#f3f6fb",
        "surface_bg": "#eef3f9",
        "card_bg": "#ffffff",
        "card_border": "#d4dce8",
        "text_fg": "#142033",
        "muted_fg": "#5c6778",
        "accent": "#0f6cbd",
        "accent_active": "#115ea3",
        "accent_fg": "#ffffff",
        "input_bg": "#ffffff",
        "input_fg": "#142033",
        "tree_bg": "#ffffff",
        "tree_fg": "#142033",
        "tree_heading_bg": "#dfe7f3",
        "tree_heading_fg": "#142033",
        "tree_selected_bg": "#b7d7f4",
        "tree_selected_fg": "#0f172a",
        "button_bg": "#dfe7f3",
        "button_fg": "#142033",
        "button_active_bg": "#cad8eb",
        "button_active_fg": "#142033",
        "status_fg": "#32506d",
        "info_fg": "#556272",
        "section_fg": "#0f172a",
        "example_fg": "#255a84",
        "empty_fg": "#8290a3",
        "canvas_bg": "#eef3f9",
    },
    "dark": {
        "app_bg": "#10161f",
        "surface_bg": "#18212d",
        "card_bg": "#1f2b3a",
        "card_border": "#334155",
        "text_fg": "#e6edf6",
        "muted_fg": "#9cafc4",
        "accent": "#5aa9ff",
        "accent_active": "#7cc0ff",
        "accent_fg": "#08111f",
        "input_bg": "#223041",
        "input_fg": "#f8fbff",
        "tree_bg": "#18212d",
        "tree_fg": "#e6edf6",
        "tree_heading_bg": "#253245",
        "tree_heading_fg": "#dbe8f7",
        "tree_selected_bg": "#36516f",
        "tree_selected_fg": "#ffffff",
        "button_bg": "#253245",
        "button_fg": "#e6edf6",
        "button_active_bg": "#314259",
        "button_active_fg": "#ffffff",
        "status_fg": "#8fc3ff",
        "info_fg": "#9cafc4",
        "section_fg": "#f8fbff",
        "example_fg": "#8fc3ff",
        "empty_fg": "#74859b",
        "canvas_bg": "#18212d",
    },
}

FONTS: dict[str, tuple[str, ...]] = {
    "body": ("Segoe UI", "10"),
    "body_bold": ("Segoe UI", "10", "bold"),
    "section": ("Segoe UI", "12", "bold"),
    "status": ("Segoe UI", "10"),
    "info": ("Segoe UI", "10"),
}


def normalize_theme_name(theme_name: str | None) -> str:
    if theme_name in THEMES:
        return str(theme_name)
    return DEFAULT_THEME


class ThemeManager:
    """Centralizes ttk and tk styling for the application."""

    def __init__(self, root: tk.Tk, theme_name: str | None = None) -> None:
        self.root = root
        self.style = ttk.Style(root)
        self.theme_name = normalize_theme_name(theme_name)
        self.palette = THEMES[self.theme_name]
        self.apply_theme()

    def set_theme(self, theme_name: str) -> None:
        self.theme_name = normalize_theme_name(theme_name)
        self.palette = THEMES[self.theme_name]
        self.apply_theme()

    def apply_theme(self) -> None:
        palette = self.palette
        self.style.theme_use("clam")
        self.root.configure(bg=palette["app_bg"])

        self.style.configure(
            ".",
            background=palette["app_bg"],
            foreground=palette["text_fg"],
            fieldbackground=palette["input_bg"],
        )
        self.style.configure("TFrame", background=palette["app_bg"])
        self.style.configure("Surface.TFrame", background=palette["surface_bg"])
        self.style.configure("TLabel", background=palette["app_bg"], foreground=palette["text_fg"], font=FONTS["body"])
        self.style.configure(
            "SectionTitle.TLabel",
            background=palette["app_bg"],
            foreground=palette["section_fg"],
            font=FONTS["section"],
        )
        self.style.configure(
            "Muted.TLabel",
            background=palette["app_bg"],
            foreground=palette["muted_fg"],
            font=FONTS["body"],
        )
        self.style.configure(
            "Status.TLabel",
            background=palette["app_bg"],
            foreground=palette["status_fg"],
            font=FONTS["status"],
        )
        self.style.configure(
            "Info.TLabel",
            background=palette["app_bg"],
            foreground=palette["info_fg"],
            font=FONTS["info"],
        )

        self.style.configure(
            "TButton",
            background=palette["button_bg"],
            foreground=palette["button_fg"],
            borderwidth=0,
            focusthickness=0,
            padding=(12, 7),
        )
        self.style.map(
            "TButton",
            background=[("active", palette["button_active_bg"])],
            foreground=[("active", palette["button_active_fg"])],
        )
        self.style.configure(
            "Accent.TButton",
            background=palette["accent"],
            foreground=palette["accent_fg"],
            borderwidth=0,
            focusthickness=0,
            padding=(12, 7),
        )
        self.style.map(
            "Accent.TButton",
            background=[("active", palette["accent_active"])],
            foreground=[("active", palette["accent_fg"])],
        )

        self.style.configure(
            "TEntry",
            fieldbackground=palette["input_bg"],
            foreground=palette["input_fg"],
            insertcolor=palette["text_fg"],
            bordercolor=palette["card_border"],
            lightcolor=palette["card_border"],
            darkcolor=palette["card_border"],
            padding=(8, 6),
        )
        self.style.configure(
            "TCombobox",
            fieldbackground=palette["input_bg"],
            foreground=palette["input_fg"],
            background=palette["button_bg"],
            arrowcolor=palette["text_fg"],
            bordercolor=palette["card_border"],
            lightcolor=palette["card_border"],
            darkcolor=palette["card_border"],
            padding=(6, 4),
        )
        self.style.map(
            "TCombobox",
            fieldbackground=[("readonly", palette["input_bg"])],
            foreground=[("readonly", palette["input_fg"])],
            selectbackground=[("readonly", palette["input_bg"])],
            selectforeground=[("readonly", palette["input_fg"])],
        )
        self.style.configure(
            "TCheckbutton",
            background=palette["app_bg"],
            foreground=palette["text_fg"],
            font=FONTS["body"],
        )
        self.style.map(
            "TCheckbutton",
            background=[("active", palette["app_bg"])],
            foreground=[("active", palette["text_fg"])],
        )

        self.style.configure("TNotebook", background=palette["app_bg"], borderwidth=0)
        self.style.configure(
            "TNotebook.Tab",
            background=palette["button_bg"],
            foreground=palette["button_fg"],
            padding=(14, 8),
            font=FONTS["body_bold"],
        )
        self.style.map(
            "TNotebook.Tab",
            background=[("selected", palette["surface_bg"]), ("active", palette["button_active_bg"])],
            foreground=[("selected", palette["text_fg"]), ("active", palette["button_active_fg"])],
        )

        self.style.configure(
            "Treeview",
            background=palette["tree_bg"],
            foreground=palette["tree_fg"],
            fieldbackground=palette["tree_bg"],
            bordercolor=palette["card_border"],
            lightcolor=palette["card_border"],
            darkcolor=palette["card_border"],
            rowheight=28,
            font=FONTS["body"],
        )
        self.style.map(
            "Treeview",
            background=[("selected", palette["tree_selected_bg"])],
            foreground=[("selected", palette["tree_selected_fg"])],
        )
        self.style.configure(
            "Treeview.Heading",
            background=palette["tree_heading_bg"],
            foreground=palette["tree_heading_fg"],
            font=FONTS["body_bold"],
            relief="flat",
            borderwidth=0,
        )
        self.style.map(
            "Treeview.Heading",
            background=[("active", palette["button_active_bg"])],
            foreground=[("active", palette["button_active_fg"])],
        )

        self.style.configure(
            "Vertical.TScrollbar",
            background=palette["button_bg"],
            troughcolor=palette["surface_bg"],
            arrowcolor=palette["text_fg"],
            bordercolor=palette["surface_bg"],
        )

    def apply_canvas(self, canvas: tk.Canvas) -> None:
        canvas.configure(
            bg=self.palette["canvas_bg"],
            highlightthickness=0,
            bd=0,
        )

    def card_tokens(self) -> dict[str, str]:
        return {
            "bg": self.palette["card_bg"],
            "border": self.palette["card_border"],
            "title_fg": self.palette["text_fg"],
            "body_fg": self.palette["muted_fg"],
            "example_fg": self.palette["example_fg"],
            "empty_fg": self.palette["empty_fg"],
        }