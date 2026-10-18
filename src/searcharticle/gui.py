"""
CustomTkinter graphical interface (dark mode).

Holds the :class:`App` class (main window) and the color theme.
All business logic (network, metadata, downloads, config) is imported
from the other package modules; this file is UI only.
"""

import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from tkinter import StringVar, filedialog

import customtkinter as ctk

from . import __version__
from .config import AppConfig, SessionState, save_config
from .downloaders import download_article
from .metadata import (
    article_from_doi,
    find_doi_by_title,
    resolve_pmid,
)
from .network import (
    diagnose_network,
    diagnostic_labels,
)
from .utils import assign_unique_names, detect_type, format_filename, sanitize_filename

# ─────────────────────────────────────────────
#  GLOBAL THEME
# ─────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ─────────────────────────────────────────────
#  COLORS
# ─────────────────────────────────────────────
C = {
    "bg": "#0f1117",  # main background
    "sidebar": "#16181f",  # sidebar
    "card": "#1c1e28",  # cards / panels
    "border": "#2a2d3e",  # subtle borders
    "accent": "#4f8ef7",  # accent blue
    "accent2": "#7c5cbf",  # secondary purple
    "success": "#3ecf8e",  # green
    "warning": "#f7c948",  # yellow
    "error": "#f75f5f",  # red
    "text": "#e2e4ef",  # main text
    "muted": "#6b7094",  # secondary text
    "input_bg": "#12141c",  # input background
}


class App(ctk.CTk):
    """Application main window."""

    def __init__(self):
        super().__init__()
        self.session = SessionState()

        self._update_title()
        self.geometry("1060x680")
        self.minsize(900, 600)
        self.configure(fg_color=C["bg"])

        self._log_queue: queue.Queue = queue.Queue()
        self._running = False
        self._total = 0
        self._done = 0

        self._build_layout()
        self._show_panel("download")
        self.after(100, self._poll_log)
        self.after(300, self._start_diagnostic)

    def _update_title(self):
        """Refresh the window title with the configured institution name."""
        name = self.session.config.institution_name.strip()
        title = f"SearchArticle {__version__}"
        if name:
            title += f" — {name}"
        self.title(title)

    # ─── LAYOUT ───────────────────────────────────────────────

    def _build_layout(self):
        # Sidebar
        self.sidebar = ctk.CTkFrame(
            self, width=220, fg_color=C["sidebar"], corner_radius=0
        )
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # Logo / title
        logo_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        logo_frame.pack(pady=(28, 0), padx=20, fill="x")
        ctk.CTkLabel(
            logo_frame,
            text="Search",
            font=ctk.CTkFont("Helvetica", 26, "bold"),
            text_color=C["accent"],
        ).pack(side="left")
        ctk.CTkLabel(
            logo_frame,
            text="Article",
            font=ctk.CTkFont("Helvetica", 16, "bold"),
            text_color=C["text"],
        ).pack(side="left")
        self.lbl_institution = ctk.CTkLabel(
            self.sidebar,
            text=self.session.config.institution_name.strip()
            or "Institutional access",
            font=ctk.CTkFont("Helvetica", 11),
            text_color=C["muted"],
        )
        self.lbl_institution.pack(pady=(0, 24), padx=20, anchor="w")

        ctk.CTkFrame(self.sidebar, height=1, fg_color=C["border"]).pack(
            fill="x", padx=16
        )

        # Nav buttons
        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        nav_items = [
            ("download", "⬇  Download"),
            ("settings", "⚙   Settings"),
        ]
        for key, label in nav_items:
            btn = ctk.CTkButton(
                self.sidebar,
                text=label,
                anchor="w",
                font=ctk.CTkFont("Helvetica", 13),
                fg_color="transparent",
                hover_color=C["border"],
                text_color=C["muted"],
                corner_radius=8,
                height=40,
                command=lambda k=key: self._show_panel(k),
            )
            btn.pack(fill="x", padx=12, pady=3)
            self._nav_buttons[key] = btn

        # Main area
        self.main_area = ctk.CTkFrame(self, fg_color=C["bg"], corner_radius=0)
        self.main_area.pack(side="left", fill="both", expand=True)

        self._panels: dict[str, ctk.CTkFrame] = {}
        self._build_panel_download()
        self._build_panel_settings()

    def _show_panel(self, key):
        for k, p in self._panels.items():
            p.pack_forget()
        self._panels[key].pack(fill="both", expand=True)
        for k, b in self._nav_buttons.items():
            b.configure(
                fg_color=C["border"] if k == key else "transparent",
                text_color=C["text"] if k == key else C["muted"],
            )

    # ─── PANEL: DOWNLOAD ──────────────────────────────────────

    def _build_panel_download(self):
        panel = ctk.CTkFrame(self.main_area, fg_color="transparent")
        self._panels["download"] = panel

        # Header
        hdr = ctk.CTkFrame(panel, fg_color="transparent")
        hdr.pack(fill="x", padx=30, pady=(28, 0))
        ctk.CTkLabel(
            hdr,
            text="Download articles",
            font=ctk.CTkFont("Helvetica", 20, "bold"),
            text_color=C["text"],
        ).pack(anchor="w")
        ctk.CTkLabel(
            hdr,
            text="DOI, PMID, title, list or BibTeX file",
            font=ctk.CTkFont("Helvetica", 12),
            text_color=C["muted"],
        ).pack(anchor="w", pady=(2, 0))

        # ── Network diagnostics banner ─────────────────────────
        self.diag_frame = ctk.CTkFrame(
            panel,
            fg_color=C["card"],
            corner_radius=10,
            border_color=C["border"],
            border_width=1,
        )
        self.diag_frame.pack(fill="x", padx=30, pady=(14, 0))

        diag_inner = ctk.CTkFrame(self.diag_frame, fg_color="transparent")
        diag_inner.pack(fill="x", padx=14, pady=10)

        # Section title + retry button
        diag_top = ctk.CTkFrame(diag_inner, fg_color="transparent")
        diag_top.pack(fill="x")
        ctk.CTkLabel(
            diag_top,
            text="Network connectivity",
            font=ctk.CTkFont("Helvetica", 11, "bold"),
            text_color=C["muted"],
        ).pack(side="left")
        ctk.CTkButton(
            diag_top,
            text="↺ Test",
            width=70,
            height=22,
            fg_color="transparent",
            hover_color=C["border"],
            text_color=C["muted"],
            font=ctk.CTkFont("Helvetica", 10),
            border_width=1,
            border_color=C["border"],
            command=self._rerun_diagnostics,
        ).pack(side="right")

        # Indicators (one per endpoint)
        self._diag_labels: dict[str, ctk.CTkLabel] = {}
        diag_row = ctk.CTkFrame(diag_inner, fg_color="transparent")
        diag_row.pack(fill="x", pady=(6, 0))
        for key, label in diagnostic_labels().items():
            cell = ctk.CTkFrame(diag_row, fg_color="transparent")
            cell.pack(side="left", padx=(0, 20))
            dot = ctk.CTkLabel(
                cell,
                text="● ",
                font=ctk.CTkFont("Helvetica", 11),
                text_color=C["muted"],
            )
            dot.pack(side="left")
            ctk.CTkLabel(
                cell,
                text=label,
                font=ctk.CTkFont("Helvetica", 11),
                text_color=C["muted"],
            ).pack(side="left")
            self._diag_labels[key] = dot

        # Input tabs
        self.tab = ctk.CTkTabview(
            panel,
            fg_color=C["card"],
            segmented_button_fg_color=C["border"],
            segmented_button_selected_color=C["accent"],
            segmented_button_selected_hover_color=C["accent"],
            segmented_button_unselected_color=C["border"],
            segmented_button_unselected_hover_color=C["border"],
            text_color=C["text"],
            border_color=C["border"],
            border_width=1,
            corner_radius=12,
        )
        self.tab.pack(fill="x", padx=30, pady=18)

        for t in ("DOI", "PMID", "Title", "Text file", "BibTeX"):
            self.tab.add(t)

        # ── DOI tab
        f = self.tab.tab("DOI")
        ctk.CTkLabel(
            f,
            text="Enter a DOI:",
            font=ctk.CTkFont("Helvetica", 12),
            text_color=C["muted"],
        ).pack(anchor="w", pady=(8, 4))
        self.doi_var = StringVar(value="10.7554/eLife.102424.3")
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(fill="x")
        ctk.CTkEntry(
            row,
            textvariable=self.doi_var,
            placeholder_text="e.g. 10.7554/eLife.102424.3",
            fg_color=C["input_bg"],
            border_color=C["border"],
            text_color=C["text"],
            font=ctk.CTkFont("Helvetica", 12),
            height=38,
        ).pack(side="left", fill="x", expand=True, padx=(0, 10))
        ctk.CTkButton(
            row,
            text="Run",
            width=100,
            height=38,
            fg_color=C["accent"],
            hover_color="#3a7ae0",
            font=ctk.CTkFont("Helvetica", 13, "bold"),
            command=self._start_doi_download,
        ).pack(side="left")

        # ── PMID tab
        f = self.tab.tab("PMID")
        ctk.CTkLabel(
            f,
            text="Enter a PMID:",
            font=ctk.CTkFont("Helvetica", 12),
            text_color=C["muted"],
        ).pack(anchor="w", pady=(8, 4))
        self.pmid_var = StringVar()
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(fill="x")
        ctk.CTkEntry(
            row,
            textvariable=self.pmid_var,
            placeholder_text="e.g. 32589966",
            fg_color=C["input_bg"],
            border_color=C["border"],
            text_color=C["text"],
            font=ctk.CTkFont("Helvetica", 12),
            height=38,
        ).pack(side="left", fill="x", expand=True, padx=(0, 10))
        ctk.CTkButton(
            row,
            text="Run",
            width=100,
            height=38,
            fg_color=C["accent"],
            hover_color="#3a7ae0",
            font=ctk.CTkFont("Helvetica", 13, "bold"),
            command=self._start_pmid_download,
        ).pack(side="left")

        # ── Title tab
        f = self.tab.tab("Title")
        ctk.CTkLabel(
            f,
            text="Enter the title (or title keywords):",
            font=ctk.CTkFont("Helvetica", 12),
            text_color=C["muted"],
        ).pack(anchor="w", pady=(8, 4))

        self.title_var = StringVar()
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(fill="x")
        ctk.CTkEntry(
            row,
            textvariable=self.title_var,
            placeholder_text="e.g. Attention is all you need",
            fg_color=C["input_bg"],
            border_color=C["border"],
            text_color=C["text"],
            font=ctk.CTkFont("Helvetica", 12),
            height=38,
        ).pack(side="left", fill="x", expand=True, padx=(0, 10))
        ctk.CTkButton(
            row,
            text="Search",
            width=120,
            height=38,
            fg_color=C["accent"],
            hover_color="#3a7ae0",
            font=ctk.CTkFont("Helvetica", 13, "bold"),
            command=self._search_title,
        ).pack(side="left")

        # Results area (scrollable, hidden until the first search)
        self.title_results_frame = ctk.CTkScrollableFrame(
            f,
            fg_color=C["input_bg"],
            corner_radius=8,
            border_color=C["border"],
            border_width=1,
            scrollbar_button_color=C["border"],
            height=120,
        )
        self.title_results_frame.pack(fill="x", pady=(10, 4))

        self.lbl_title_status = ctk.CTkLabel(
            f,
            text="",
            font=ctk.CTkFont("Helvetica", 11),
            text_color=C["muted"],
            anchor="w",
        )
        self.lbl_title_status.pack(anchor="w", pady=(2, 0))

        # Store current results
        self._title_results: list[dict] = []
        self._title_result_widgets: list = []

        # ── Text file tab
        f = self.tab.tab("Text file")
        ctk.CTkLabel(
            f,
            text="One DOI or PMID per line:",
            font=ctk.CTkFont("Helvetica", 12),
            text_color=C["muted"],
        ).pack(anchor="w", pady=(8, 4))
        self.txt_path_var = StringVar()
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(fill="x")
        ctk.CTkEntry(
            row,
            textvariable=self.txt_path_var,
            placeholder_text="Path to the .txt file",
            fg_color=C["input_bg"],
            border_color=C["border"],
            text_color=C["text"],
            font=ctk.CTkFont("Helvetica", 12),
            height=38,
        ).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(
            row,
            text="Browse",
            width=90,
            height=38,
            fg_color=C["border"],
            hover_color="#3a3d55",
            text_color=C["text"],
            font=ctk.CTkFont("Helvetica", 12),
            command=lambda: self._browse(
                self.txt_path_var, [("Text files", "*.txt")]
            ),
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            row,
            text="Run",
            width=90,
            height=38,
            fg_color=C["accent"],
            hover_color="#3a7ae0",
            font=ctk.CTkFont("Helvetica", 13, "bold"),
            command=self._start_txt_download,
        ).pack(side="left")

        # ── BibTeX tab
        f = self.tab.tab("BibTeX")
        ctk.CTkLabel(
            f,
            text="Select a .bib file:",
            font=ctk.CTkFont("Helvetica", 12),
            text_color=C["muted"],
        ).pack(anchor="w", pady=(8, 4))
        self.bib_path_var = StringVar()
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(fill="x")
        ctk.CTkEntry(
            row,
            textvariable=self.bib_path_var,
            placeholder_text="Path to the .bib file",
            fg_color=C["input_bg"],
            border_color=C["border"],
            text_color=C["text"],
            font=ctk.CTkFont("Helvetica", 12),
            height=38,
        ).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(
            row,
            text="Browse",
            width=90,
            height=38,
            fg_color=C["border"],
            hover_color="#3a3d55",
            text_color=C["text"],
            font=ctk.CTkFont("Helvetica", 12),
            command=lambda: self._browse(
                self.bib_path_var, [("BibTeX", "*.bib")]
            ),
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            row,
            text="Run",
            width=90,
            height=38,
            fg_color=C["accent"],
            hover_color="#3a7ae0",
            font=ctk.CTkFont("Helvetica", 13, "bold"),
            command=self._start_bib_download,
        ).pack(side="left")

        # Progress bar + stats
        prog_frame = ctk.CTkFrame(
            panel,
            fg_color=C["card"],
            corner_radius=12,
            border_color=C["border"],
            border_width=1,
        )
        prog_frame.pack(fill="x", padx=30, pady=(0, 14))
        inner = ctk.CTkFrame(prog_frame, fg_color="transparent")
        inner.pack(fill="x", padx=18, pady=14)

        self.prog_bar = ctk.CTkProgressBar(
            inner, height=8, progress_color=C["accent"], fg_color=C["border"]
        )
        self.prog_bar.pack(fill="x")
        self.prog_bar.set(0)

        stats_row = ctk.CTkFrame(inner, fg_color="transparent")
        stats_row.pack(fill="x", pady=(8, 0))
        self.lbl_prog = ctk.CTkLabel(
            stats_row,
            text="Waiting",
            font=ctk.CTkFont("Helvetica", 11),
            text_color=C["muted"],
        )
        self.lbl_prog.pack(side="left")
        self.lbl_stats = ctk.CTkLabel(
            stats_row,
            text="",
            font=ctk.CTkFont("Helvetica", 11),
            text_color=C["muted"],
        )
        self.lbl_stats.pack(side="right")

        # Log console
        ctk.CTkLabel(
            panel,
            text="Log",
            font=ctk.CTkFont("Helvetica", 12, "bold"),
            text_color=C["muted"],
        ).pack(anchor="w", padx=30)

        log_frame = ctk.CTkFrame(
            panel,
            fg_color=C["input_bg"],
            corner_radius=12,
            border_color=C["border"],
            border_width=1,
        )
        log_frame.pack(fill="both", expand=True, padx=30, pady=(4, 20))

        self.log_box = ctk.CTkTextbox(
            log_frame,
            fg_color="transparent",
            text_color=C["text"],
            font=ctk.CTkFont("Courier", 12),
            scrollbar_button_color=C["border"],
            wrap="word",
            state="disabled",
        )
        self.log_box.pack(fill="both", expand=True, padx=6, pady=6)

        # Tag colors
        self.log_box._textbox.tag_config("success", foreground=C["success"])
        self.log_box._textbox.tag_config("error", foreground=C["error"])
        self.log_box._textbox.tag_config("warning", foreground=C["warning"])
        self.log_box._textbox.tag_config("muted", foreground=C["muted"])
        self.log_box._textbox.tag_config("accent", foreground=C["accent"])
        self.log_box._textbox.tag_config("normal", foreground=C["text"])

        # Bottom buttons
        btn_row = ctk.CTkFrame(panel, fg_color="transparent")
        btn_row.pack(fill="x", padx=30, pady=(0, 20))
        ctk.CTkButton(
            btn_row,
            text="Open folder",
            width=160,
            height=34,
            fg_color=C["border"],
            hover_color="#3a3d55",
            text_color=C["text"],
            font=ctk.CTkFont("Helvetica", 12),
            command=self._open_folder,
        ).pack(side="left", padx=(0, 10))
        ctk.CTkButton(
            btn_row,
            text="Clear log",
            width=150,
            height=34,
            fg_color="transparent",
            hover_color=C["border"],
            text_color=C["muted"],
            font=ctk.CTkFont("Helvetica", 12),
            command=self._clear_log,
        ).pack(side="left")

    # ─── PANEL: SETTINGS ──────────────────────────────────────

    def _build_panel_settings(self):
        panel = ctk.CTkFrame(self.main_area, fg_color="transparent")
        self._panels["settings"] = panel

        hdr = ctk.CTkFrame(panel, fg_color="transparent")
        hdr.pack(fill="x", padx=30, pady=(28, 0))
        ctk.CTkLabel(
            hdr,
            text="Settings",
            font=ctk.CTkFont("Helvetica", 20, "bold"),
            text_color=C["text"],
        ).pack(anchor="w")
        ctk.CTkLabel(
            hdr,
            text="Configuration saved in config.json",
            font=ctk.CTkFont("Helvetica", 12),
            text_color=C["muted"],
        ).pack(anchor="w", pady=(2, 0))

        scroll = ctk.CTkScrollableFrame(
            panel, fg_color="transparent", scrollbar_button_color=C["border"]
        )
        scroll.pack(fill="both", expand=True, padx=30, pady=16)

        def section(title):
            ctk.CTkLabel(
                scroll,
                text=title,
                font=ctk.CTkFont("Helvetica", 13, "bold"),
                text_color=C["accent"],
            ).pack(anchor="w", pady=(18, 6))
            ctk.CTkFrame(scroll, height=1, fg_color=C["border"]).pack(
                fill="x", pady=(0, 10)
            )

        def field(label, var, placeholder="", show=""):
            f = ctk.CTkFrame(scroll, fg_color="transparent")
            f.pack(fill="x", pady=4)
            ctk.CTkLabel(
                f,
                text=label,
                width=160,
                anchor="w",
                font=ctk.CTkFont("Helvetica", 12),
                text_color=C["text"],
            ).pack(side="left")
            ctk.CTkEntry(
                f,
                textvariable=var,
                placeholder_text=placeholder,
                fg_color=C["input_bg"],
                border_color=C["border"],
                text_color=C["text"],
                font=ctk.CTkFont("Helvetica", 12),
                show=show,
                height=36,
            ).pack(side="left", fill="x", expand=True)

        def folder_field(label, var):
            f = ctk.CTkFrame(scroll, fg_color="transparent")
            f.pack(fill="x", pady=4)
            ctk.CTkLabel(
                f,
                text=label,
                width=160,
                anchor="w",
                font=ctk.CTkFont("Helvetica", 12),
                text_color=C["text"],
            ).pack(side="left")
            ctk.CTkEntry(
                f,
                textvariable=var,
                fg_color=C["input_bg"],
                border_color=C["border"],
                text_color=C["text"],
                font=ctk.CTkFont("Helvetica", 12),
                height=36,
            ).pack(side="left", fill="x", expand=True, padx=(0, 8))
            ctk.CTkButton(
                f,
                text="📂",
                width=38,
                height=36,
                fg_color=C["border"],
                hover_color="#3a3d55",
                text_color=C["text"],
                command=lambda: self._browse_folder(var),
            ).pack(side="left")

        cfg = self.session.config
        self.sv_email = StringVar(value=cfg.email)
        self.sv_folder = StringVar(value=cfg.output_folder)
        self.sv_institution_name = StringVar(value=cfg.institution_name)
        self.sv_institution_ip_prefix = StringVar(value=cfg.institution_ip_prefix)

        section("General")
        field(
            "Email (required for Unpaywall)",
            self.sv_email,
            "firstname.lastname@university.edu",
        )
        folder_field("Output folder", self.sv_folder)

        section("Institutional access")
        field(
            "Institution name",
            self.sv_institution_name,
            "e.g. Sorbonne Université",
        )
        field(
            "Institution IP prefix",
            self.sv_institution_ip_prefix,
            "e.g. 132.204.",
        )
        ctk.CTkLabel(
            scroll,
            text="Used to detect your institution's network/VPN for publisher "
            "access. Leave empty to skip the proxy check.",
            font=ctk.CTkFont("Helvetica", 11),
            text_color=C["muted"],
            wraplength=620,
            justify="left",
        ).pack(anchor="w", pady=(2, 0))

        # Save button
        self.lbl_save_status = ctk.CTkLabel(
            scroll, text="", font=ctk.CTkFont("Helvetica", 12), text_color=C["success"]
        )
        self.lbl_save_status.pack(anchor="w", pady=(8, 0))
        ctk.CTkButton(
            scroll,
            text="💾  Save",
            height=40,
            fg_color=C["accent"],
            hover_color="#3a7ae0",
            font=ctk.CTkFont("Helvetica", 13, "bold"),
            command=self._save_settings,
        ).pack(anchor="w", pady=(6, 20))

    # ─── ACTIONS ──────────────────────────────────────────────

    def _browse(self, var, filetypes):
        p = filedialog.askopenfilename(filetypes=filetypes)
        if p:
            var.set(p)

    def _browse_folder(self, var):
        p = filedialog.askdirectory()
        if p:
            var.set(p)

    # ─── NETWORK DIAGNOSTICS ──────────────────────────────────

    def _start_diagnostic(self):
        # Reset all dots to "in progress"
        for dot in self._diag_labels.values():
            dot.configure(text="● ", text_color=C["muted"])
        # The proxy check is skipped when no IP prefix is configured:
        # mark its dot as "not applicable" instead of "in progress".
        if not self.session.config.institution_ip_prefix.strip():
            dot = self._diag_labels.get("proxy")
            if dot:
                dot.configure(text="○ ", text_color=C["muted"])
        threading.Thread(target=self._run_diagnostic, daemon=True).start()

    def _rerun_diagnostics(self):
        self._start_diagnostic()

    def _run_diagnostic(self):
        def cb(key, ok):
            self.after(0, self._on_diag_result, key, ok)

        diagnose_network(self.session, callback=cb)

    def _on_diag_result(self, key: str, ok: bool):
        dot = self._diag_labels.get(key)
        if not dot:
            return
        if ok:
            dot.configure(text="● ", text_color=C["success"])
        else:
            dot.configure(text="● ", text_color=C["error"])
            # Targeted warning in the log, per service
            inst_name = self.session.config.institution_name.strip()
            if inst_name:
                proxy_tip = (
                    f"⚠  {inst_name} proxy not detected — you are off campus/VPN: "
                    "subscription articles will be unreachable via the publisher."
                )
                doi_tip = (
                    "⚠  DOI resolver unreachable — publisher downloads "
                    f"will fail.\n   → Connect to the {inst_name} VPN."
                )
            else:
                proxy_tip = (
                    "⚠  Institutional proxy not detected — subscription articles "
                    "may be unreachable via the publisher "
                    "(set your institution in Settings)."
                )
                doi_tip = (
                    "⚠  DOI resolver unreachable — publisher downloads "
                    "will fail.\n   → Connect to your institution's VPN."
                )
            tips = {
                "internet": "⚠  No Internet access — check your WiFi/Ethernet connection.",
                "proxy": proxy_tip,
                "doi": doi_tip,
                "ncbi": "⚠  NCBI / PMC unreachable — PMC downloads will be skipped.",
                "unpaywall": "⚠  Unpaywall unreachable — this source will be skipped.",
            }
            if key in tips:
                self._log(tips[key], "warning")

    def _open_folder(self):
        d = self.session.output_folder
        if sys.platform == "win32":
            import os

            os.startfile(d)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", d])
        else:
            subprocess.Popen(["xdg-open", d])

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _save_settings(self):
        cfg = AppConfig(
            email=self.sv_email.get().strip(),
            output_folder=self.sv_folder.get().strip(),
            institution_name=self.sv_institution_name.get().strip(),
            institution_ip_prefix=self.sv_institution_ip_prefix.get().strip(),
        )
        save_config(cfg)
        self.session.apply(cfg)
        # Refresh institution-dependent UI and re-run diagnostics so the
        # proxy check uses the new IP prefix immediately.
        self._update_title()
        self.lbl_institution.configure(
            text=cfg.institution_name.strip() or "Institutional access"
        )
        self._start_diagnostic()
        self.lbl_save_status.configure(text="✔  Saved!")
        self.after(2500, lambda: self.lbl_save_status.configure(text=""))

    # ─── LOG ──────────────────────────────────────────────────

    def _log(self, msg, style="normal"):
        self._log_queue.put((msg, style))

    def _poll_log(self):
        try:
            while True:
                msg, style = self._log_queue.get_nowait()
                self.log_box.configure(state="normal")
                self.log_box._textbox.insert("end", msg + "\n", style)
                self.log_box.see("end")
                self.log_box.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(80, self._poll_log)

    # ─── PROGRESS ─────────────────────────────────────────────

    def _update_prog(self, done, total, succeeded, failed):
        self._done = done
        self._total = total
        ratio = done / total if total else 0
        self.prog_bar.set(ratio)
        self.lbl_prog.configure(
            text=f"{done} / {total} articles", text_color=C["text"]
        )
        self.lbl_stats.configure(text=f"✔ {succeeded}   ✘ {failed}", text_color=C["text"])

    # ─── DOWNLOADS ────────────────────────────────────────────

    def _start_doi_download(self):
        doi = self.doi_var.get().strip()
        if not doi:
            self._log("⚠  Empty DOI.", "warning")
            return
        _, d = detect_type(doi)
        if not d.startswith("10."):
            self._log("⚠  Invalid DOI (must start with 10.)", "warning")
            return

        def run():
            self._log(f"🔎 Resolving CrossRef metadata for {d}…", "accent")
            article = article_from_doi(d)
            if article.get("author") and article.get("year"):
                self._log(
                    f"  ✔  {article['author']} et al., {article['year']}"
                    f" — {article['full_title'][:60]}",
                    "success",
                )
            else:
                self._log(
                    "  ⚠  Incomplete metadata, DOI-based filename",
                    "warning",
                )
            self.after(0, self._start_downloads, [article])

        threading.Thread(target=run, daemon=True).start()

    def _start_pmid_download(self):
        pmid = self.pmid_var.get().strip()
        if not pmid.isdigit():
            self._log("⚠  Invalid PMID (digits only).", "warning")
            return

        def run():
            self._log(f"🔎 Resolving PMID {pmid}…", "accent")
            article = resolve_pmid(pmid) or {
                "title": sanitize_filename(f"PMID_{pmid}"),
                "full_title": f"PMID {pmid}",
                "doi": None,
                "pmid": pmid,
                "author": "",
                "year": "",
            }
            if article.get("doi"):
                self._log(f"  ✔  DOI: {article['doi']}", "success")
            else:
                self._log("  ⚠  No DOI, trying PMC directly", "warning")
            self.after(0, self._start_downloads, [article])

        threading.Thread(target=run, daemon=True).start()

    # ── Title search ───────────────────────────────────────────

    def _search_title(self):
        q = self.title_var.get().strip()
        if not q:
            self.lbl_title_status.configure(text="⚠  Empty title.", text_color=C["warning"])
            return
        # Clear previous results
        for w in self._title_result_widgets:
            w.destroy()
        self._title_result_widgets.clear()
        self._title_results.clear()
        self.lbl_title_status.configure(
            text="🔎 Searching…", text_color=C["muted"]
        )

        def run():
            results = find_doi_by_title(q, max_results=5)
            self.after(0, self._display_title_results, results)

        threading.Thread(target=run, daemon=True).start()

    def _display_title_results(self, results: list[dict]):
        # Clear old widgets first
        for w in self._title_result_widgets:
            w.destroy()
        self._title_result_widgets.clear()
        self._title_results = results

        if not results:
            self.lbl_title_status.configure(
                text="✘  No results found. Try different keywords.",
                text_color=C["error"],
            )
            return

        self.lbl_title_status.configure(
            text=f"✔  {len(results)} result(s) — click an article to download it",
            text_color=C["success"],
        )

        for i, result in enumerate(results):
            # Clickable card per result
            card = ctk.CTkFrame(
                self.title_results_frame,
                fg_color=C["card"],
                corner_radius=8,
                border_color=C["border"],
                border_width=1,
            )
            card.pack(fill="x", padx=4, pady=3)

            # Row 1: title + source badge
            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=10, pady=(8, 2))
            short_title = result["title"][:80] + ("…" if len(result["title"]) > 80 else "")
            ctk.CTkLabel(
                top,
                text=short_title,
                font=ctk.CTkFont("Helvetica", 12, "bold"),
                text_color=C["text"],
                anchor="w",
                wraplength=520,
                justify="left",
            ).pack(side="left", fill="x", expand=True)

            badge_color = C["accent"] if result["source"] == "CrossRef" else C["accent2"]
            ctk.CTkLabel(
                top,
                text=result["source"],
                font=ctk.CTkFont("Helvetica", 10),
                fg_color=badge_color,
                text_color="white",
                corner_radius=4,
                padx=6,
                pady=1,
            ).pack(side="right", padx=(6, 0))

            # Row 2: authors, year, journal, DOI
            meta_parts = []
            if result.get("authors"):
                meta_parts.append(result["authors"])
            if result.get("year"):
                meta_parts.append(result["year"])
            if result.get("journal"):
                meta_parts.append(result["journal"])
            meta_str = "  ·  ".join(meta_parts)

            ctk.CTkLabel(
                card,
                text=meta_str,
                font=ctk.CTkFont("Helvetica", 11),
                text_color=C["muted"],
                anchor="w",
            ).pack(fill="x", padx=10, pady=(0, 4))

            # Row 3: DOI + download button
            bottom = ctk.CTkFrame(card, fg_color="transparent")
            bottom.pack(fill="x", padx=10, pady=(0, 8))

            doi_txt = result.get("doi") or "DOI not available"
            doi_color = C["muted"] if result.get("doi") else C["error"]
            ctk.CTkLabel(
                bottom,
                text=doi_txt,
                font=ctk.CTkFont("Courier", 11),
                text_color=doi_color,
                anchor="w",
            ).pack(side="left")

            ctk.CTkButton(
                bottom,
                text="⬇  Download",
                width=130,
                height=28,
                fg_color=C["accent"] if result.get("doi") else C["border"],
                hover_color="#3a7ae0" if result.get("doi") else C["border"],
                text_color="white" if result.get("doi") else C["muted"],
                font=ctk.CTkFont("Helvetica", 11, "bold"),
                state="normal" if result.get("doi") else "disabled",
                command=lambda r=result: self._download_from_result(r),
            ).pack(side="right")

            self._title_result_widgets.append(card)

    def _download_from_result(self, result: dict):
        """Start the download from a title-search result."""
        doi = result.get("doi")
        pmid = result.get("pmid")
        title = result.get("title", doi or "article")

        name = format_filename(
            result.get("authors", "").split(",")[0].strip(),
            result.get("year", ""),
            title[:50],
        )
        article = {
            "title": name,
            "full_title": title,
            "doi": doi,
            "pmid": pmid,
            "author": result.get("authors", "").split(",")[0].strip(),
            "year": result.get("year", ""),
        }
        self._start_downloads([article])

    def _start_txt_download(self):
        f = self.txt_path_var.get().strip()
        if not f or not Path(f).exists():
            self._log("⚠  File not found.", "warning")
            return

        def run():
            self._log(f"📖 Reading {Path(f).name}…", "accent")
            articles = self._parse_txt(f)
            if articles:
                self.after(0, self._start_downloads, articles)

        threading.Thread(target=run, daemon=True).start()

    def _start_bib_download(self):
        f = self.bib_path_var.get().strip()
        if not f or not Path(f).exists():
            self._log("⚠  File not found.", "warning")
            return

        def run():
            self._log(f"📖 Reading {Path(f).name}…", "accent")
            articles = self._parse_bib(f)
            if articles:
                self.after(0, self._start_downloads, articles)

        threading.Thread(target=run, daemon=True).start()

    def _parse_txt(self, file_path):
        lines = Path(file_path).read_text(encoding="utf-8").splitlines()
        articles, unrecognized = [], []
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            t, v = detect_type(line)
            if t == "doi":
                articles.append(article_from_doi(v))
            elif t == "pmid":
                self._log(f"  🔎 Resolving PMID {v}…", "muted")
                article = resolve_pmid(v) or {
                    "title": sanitize_filename(f"PMID_{v}"),
                    "full_title": f"PMID {v}",
                    "doi": None,
                    "pmid": v,
                    "author": "",
                    "year": "",
                }
                articles.append(article)
                time.sleep(0.4)
            else:
                unrecognized.append(line)
        if unrecognized:
            self._log(f"⚠  {len(unrecognized)} unrecognized line(s)", "warning")
        self._log(f"✔  {len(articles)} identifier(s) found", "success")
        return articles

    def _parse_bib(self, file_path):
        content = Path(file_path).read_text(encoding="utf-8")
        articles = []
        for i, entry in enumerate(re.split(r"@\w+\{", content)[1:], 1):
            title_m = re.search(
                r'title\s*=\s*[{"](.*?)[}"]', entry, re.IGNORECASE | re.DOTALL
            )
            title = (
                re.sub(r"[{}]", "", title_m.group(1).strip() if title_m else f"Untitled_{i}")[
                    :100
                ]
            )
            doi_m = re.search(r'doi\s*=\s*[{"](.*?)[}"]', entry, re.IGNORECASE)
            doi = doi_m.group(1).strip() if doi_m else None
            author_m = re.search(r'author\s*=\s*[{"](.*?)[}"]', entry, re.IGNORECASE)
            author = (
                author_m.group(1).split(" and ")[0].split(",")[0].strip() if author_m else ""
            )
            year_m = re.search(r'year\s*=\s*[{"]*(\d{4})[}"]', entry, re.IGNORECASE)
            year = year_m.group(1) if year_m else ""
            journal_m = re.search(r'journal\s*=\s*[{"](.*?)[}"]', entry, re.IGNORECASE)
            journal = re.sub(r"[{}]", "", journal_m.group(1).strip() if journal_m else "")
            name = format_filename(author, year, title[:50])
            articles.append(
                {
                    "title": name,
                    "full_title": title,
                    "doi": doi,
                    "pmid": None,
                    "author": author,
                    "year": year,
                    "journal": journal,
                }
            )
        self._log(f"✔  {len(articles)} articles in the BibTeX", "success")
        return articles

    def _start_downloads(self, articles):
        if self._running:
            self._log("⚠  A download is already running.", "warning")
            return
        if not articles:
            self._log("⚠  No articles to process.", "warning")
            return

        n = len(articles)
        n_doi = sum(1 for a in articles if a.get("doi"))
        n_pm = sum(1 for a in articles if a.get("pmid"))
        self._log(f"\n{'─'*54}", "muted")
        self._log(
            f"🚀 Starting — {n} article(s)  ·  DOI: {n_doi}  ·  PMID: {n_pm}", "accent"
        )
        self._log(f"{'─'*54}", "muted")

        # Avoid name collisions (same author, same year → a/b/c suffixes)
        n_renamed = assign_unique_names(articles)
        if n_renamed:
            self._log(
                f"📌 {n_renamed} article(s) renamed (a/b/c): "
                "same author and year",
                "muted",
            )

        threading.Thread(
            target=self._run_downloads, args=(articles,), daemon=True
        ).start()

    def _run_downloads(self, articles):
        self._running = True
        succeeded = failed = 0
        total = len(articles)
        self.after(0, self._update_prog, 0, total, 0, 0)

        for i, article in enumerate(articles, 1):
            title = article.get("full_title", article["title"])[:60]
            self._log(f"\n[{i}/{total}] {title}", "normal")
            if article.get("doi"):
                self._log(f"  DOI  : {article['doi']}", "muted")
            if article.get("pmid"):
                self._log(f"  PMID : {article['pmid']}", "muted")

            ok = download_article(article, self.session, self._log)
            if ok:
                succeeded += 1
            else:
                failed += 1
            self.after(0, self._update_prog, i, total, succeeded, failed)
            if i < total:
                time.sleep(2)

        self._log(f"\n{'─'*54}", "muted")
        self._log(
            f"✔  Done  ·  {succeeded} succeeded  ·  {failed} failed", "success"
        )
        self._log(f"📁 {self.session.output_folder}", "muted")
        self._log(f"{'─'*54}", "muted")
        self._running = False
