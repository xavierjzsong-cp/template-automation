from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from src.services.template_generation_service import (
    GenerationRequest,
    TemplateGenerationService,
)

from src.ui.styles import AppStyle
from src.utils.app_paths import configure_playwright_browsers, settings_path


class TemplateAutomationApp(AppStyle, ctk.CTk):

    SETTINGS_PATH = settings_path()

    TEMPLATE_SHEET_OPTIONS = [
        f"CP_ACCESSORY-{index:02d}"
        for index in range(1, 21)
    ]

    def __init__(self) -> None:
        configure_playwright_browsers()

        super().__init__()

        self.title("Template Automation Tool")
        self.geometry("860x680")
        self.minsize(780, 640)
        self.configure(fg_color=self.COLOR_BACKGROUND)

        ctk.set_appearance_mode("Light")
        ctk.set_default_color_theme("blue")

        self.service = TemplateGenerationService()
        self.last_output_file: str | None = None

        self.user_name_var = ctk.StringVar()
        self.input_pdf_var = ctk.StringVar()
        self.template_file_var = ctk.StringVar()
        self.target_sheet_var = ctk.StringVar(value=self.TEMPLATE_SHEET_OPTIONS[0])
        self.output_dir_var = ctk.StringVar()
        self.show_browser_var = ctk.BooleanVar(value=True)

        self.progress_var = ctk.DoubleVar(value=0)
        self.progress_percent_var = ctk.StringVar(value="0%")

        self.generation_started = False
        self.browser_warmup_started = False
        self.browser_warmup_running = False

        self.target_sheet_dropdown_visible = False
        self.target_sheet_result_widgets: list[ctk.CTkBaseClass] = []

        self._load_settings()
        self._build_ui()

        self.after(1000, self._start_browser_warmup_if_idle)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(
            self,
            corner_radius=0,
            fg_color=self.COLOR_BACKGROUND,
        )
        header.grid(row=0, column=0, sticky="ew", padx=0, pady=0)

        title = ctk.CTkLabel(
            header,
            text="Template Automation Tool",
            font=ctk.CTkFont(size=26, weight="bold"),
            text_color=self.COLOR_TEXT,
        )
        title.pack(anchor="w", padx=28, pady=(22, 18))

        main = ctk.CTkFrame(
            self,
            fg_color=self.COLOR_CARD,
            corner_radius=12,
            border_width=1,
            border_color=self.COLOR_BORDER,
        )
        main.grid(row=1, column=0, sticky="nsew", padx=28, pady=(0, 24))
        main.grid_columnconfigure(1, weight=0)
        main.grid_columnconfigure(2, weight=0)
        main.grid_columnconfigure(3, weight=1)

        for row_index in range(10):
            main.grid_rowconfigure(row_index, weight=0)
        main.grid_rowconfigure(9, weight=1)

        section_title = ctk.CTkLabel(
            main,
            text="Input Settings",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=self.COLOR_TEXT,
        )
        section_title.grid(row=0, column=0, columnspan=3, sticky="w", padx=24, pady=(22, 10))

        self._add_label(main, "User Name", row=1)
        user_entry = self._create_entry(main, self.user_name_var)
        user_entry.grid(row=1, column=1, sticky="w", padx=(14, 24), pady=8)

        self._add_label(main, "Input POTS File", row=2)
        input_entry = self._create_entry(main, self.input_pdf_var)
        input_entry.grid(row=2, column=1, sticky="w", padx=(14, 10), pady=8)
        input_button = self._create_primary_button(
            main,
            text="Browse",
            width=self.BROWSE_BUTTON_WIDTH,
            height=self.BROWSE_BUTTON_HEIGHT,
            command=self._browse_input_pdf,
        )
        input_button.grid(row=2, column=2, sticky="e", padx=(0, 24), pady=8)

        self._add_label(main, "Template Excel File", row=3)
        template_entry = self._create_entry(main, self.template_file_var)
        template_entry.grid(row=3, column=1, sticky="w", padx=(14, 10), pady=8)
        template_button = self._create_primary_button(
            main,
            text="Browse",
            width=self.BROWSE_BUTTON_WIDTH,
            height=self.BROWSE_BUTTON_HEIGHT,
            command=self._browse_template_file,
        )
        template_button.grid(row=3, column=2, sticky="e", padx=(0, 24), pady=8)

        self._add_label(main, "Target Sheet", row=4)

        target_sheet_input_frame = ctk.CTkFrame(
            main,
            width=self.TARGET_SHEET_WIDTH,
            height=self.FIELD_HEIGHT,
            fg_color="transparent",
        )
        target_sheet_input_frame.grid(
            row=4,
            column=1,
            sticky="w",
            padx=(14, 24),
            pady=8,
        )
        target_sheet_input_frame.grid_propagate(False)
        target_sheet_input_frame.grid_columnconfigure(0, weight=1)

        self.target_sheet_entry = ctk.CTkEntry(
            target_sheet_input_frame,
            textvariable=self.target_sheet_var,
            height=self.FIELD_HEIGHT,
            border_color=self.COLOR_BORDER,
            fg_color="#FFFFFF",
            text_color=self.COLOR_TEXT,
        )
        self.target_sheet_entry.grid(row=0, column=0, sticky="ew")

        self.target_sheet_entry.bind(
            "<FocusIn>",
            lambda event: self._show_target_sheet_dropdown(show_all=False),
        )
        self.target_sheet_entry.bind(
            "<KeyRelease>",
            lambda event: self._on_target_sheet_input_changed(),
        )
        self.target_sheet_entry.bind(
            "<Escape>",
            lambda event: self._hide_target_sheet_dropdown(),
        )

        self.target_sheet_dropdown_button = ctk.CTkButton(
            target_sheet_input_frame,
            text="▼",
            width=42,
            height=self.FIELD_HEIGHT,
            fg_color=self.COLOR_PRIMARY,
            hover_color=self.COLOR_PRIMARY_HOVER,
            text_color="#FFFFFF",
            command=self._toggle_target_sheet_dropdown,
        )
        self.target_sheet_dropdown_button.grid(row=0, column=1, sticky="e", padx=(8, 0))

        self.target_sheet_dropdown = ctk.CTkFrame(
            main,
            width=self.TARGET_SHEET_WIDTH,
            fg_color="#FFFFFF",
            corner_radius=8,
            border_width=1,
            border_color=self.COLOR_BORDER,
        )
        self.target_sheet_dropdown.grid_columnconfigure(0, weight=1)

        self.target_sheet_results_frame = ctk.CTkScrollableFrame(
            self.target_sheet_dropdown,
            width=self.TARGET_SHEET_WIDTH - 20,
            fg_color="#FFFFFF",
            corner_radius=6,
            height=self.TARGET_SHEET_DROPDOWN_HEIGHT,
        )
        self.target_sheet_results_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        self.target_sheet_results_frame.grid_columnconfigure(0, weight=1)

        self._add_label(main, "Output Folder", row=6)
        output_entry = self._create_entry(main, self.output_dir_var)
        output_entry.grid(row=6, column=1, sticky="w", padx=(14, 10), pady=8)
        output_button = self._create_primary_button(
            main,
            text="Browse",
            width=self.BROWSE_BUTTON_WIDTH,
            height=self.BROWSE_BUTTON_HEIGHT,
            command=self._browse_output_dir,
        )
        output_button.grid(row=6, column=2, sticky="e", padx=(0, 24), pady=8)

        options_frame = ctk.CTkFrame(main, fg_color="transparent")
        options_frame.grid(row=7, column=1, columnspan=2, sticky="w", padx=(14, 24), pady=(10, 8))

        show_browser_checkbox = ctk.CTkCheckBox(
            options_frame,
            text="Show browser during automation",
            variable=self.show_browser_var,
            fg_color=self.COLOR_PRIMARY,
            hover_color=self.COLOR_PRIMARY_HOVER,
            border_color=self.COLOR_MUTED,
            text_color=self.COLOR_TEXT,
            command=self._save_settings,
        )
        show_browser_checkbox.pack(anchor="w")

        button_frame = ctk.CTkFrame(main, fg_color="transparent")
        button_frame.grid(row=8, column=0, columnspan=3, sticky="ew", padx=24, pady=(20, 16))
        button_frame.grid_columnconfigure(0, weight=1)

        self.generate_button = self._create_primary_button(
            button_frame,
            text="Generate Template",
            height=self.PRIMARY_BUTTON_HEIGHT,
            command=self._start_generation,
        )
        self.generate_button.grid(row=0, column=0, sticky="ew", padx=(0, 10))

        self.open_output_button = ctk.CTkButton(
            button_frame,
            text="Open Output Folder",
            height=self.PRIMARY_BUTTON_HEIGHT,
            width=170,
            fg_color=self.COLOR_SECONDARY,
            hover_color="#D7EAF5",
            text_color=self.COLOR_PRIMARY,
            state="disabled",
            command=self._open_output_folder,
        )
        self.open_output_button.grid(row=0, column=1, sticky="e")

        self.progress_card = ctk.CTkFrame(
            main,
            fg_color=self.COLOR_BACKGROUND,
            corner_radius=10,
            border_width=1,
            border_color=self.COLOR_BORDER,
        )
        self.progress_card.grid_columnconfigure(0, weight=1)

        progress_header = ctk.CTkFrame(self.progress_card, fg_color="transparent")
        progress_header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 6))
        progress_header.grid_columnconfigure(0, weight=1)

        progress_title = ctk.CTkLabel(
            progress_header,
            text="Progress",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=self.COLOR_TEXT,
        )
        progress_title.grid(row=0, column=0, sticky="w")

        self.progress_percent_label = ctk.CTkLabel(
            progress_header,
            textvariable=self.progress_percent_var,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=self.COLOR_PRIMARY,
        )
        self.progress_percent_label.grid(row=0, column=1, sticky="e")

        self.progress_bar = ctk.CTkProgressBar(
            self.progress_card,
            height=self.PROGRESS_BAR_HEIGHT,
            progress_color=self.COLOR_PRIMARY,
            fg_color=self.COLOR_BORDER,
        )
        self.progress_bar.grid(row=1, column=0, sticky="ew", padx=18, pady=(4, 10))
        self.progress_bar.set(0)

        self.status_message_label = ctk.CTkLabel(
            self.progress_card,
            text="Ready.",
            font=ctk.CTkFont(size=13),
            text_color=self.COLOR_MUTED,
            anchor="w",
            justify="left",
            height=self.STATUS_MESSAGE_HEIGHT,
        )
        self.status_message_label.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 16))

    def _add_label(self, parent, text: str, row: int) -> None:
        label = ctk.CTkLabel(
            parent,
            text=text,
            anchor="w",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=self.COLOR_TEXT,
        )
        label.grid(row=row, column=0, sticky="w", padx=(24, 0), pady=8)

    def _create_entry(self, parent, variable: ctk.StringVar) -> ctk.CTkEntry:
        return ctk.CTkEntry(
            parent,
            textvariable=variable,
            width=self.FIELD_WIDTH,
            height=self.FIELD_HEIGHT,
            border_color=self.COLOR_BORDER,
            fg_color="#FFFFFF",
            text_color=self.COLOR_TEXT,
        )

    def _create_primary_button(
        self,
        parent,
        text: str,
        command,
        width: int | None = None,
        height: int | None = None,
    ) -> ctk.CTkButton:
        button_kwargs = {
            "master": parent,
            "text": text,
            "height": height if height is not None else self.FIELD_HEIGHT,
            "fg_color": self.COLOR_PRIMARY,
            "hover_color": self.COLOR_PRIMARY_HOVER,
            "text_color": "#FFFFFF",
            "command": command,
        }

        if width is not None:
            button_kwargs["width"] = width

        return ctk.CTkButton(**button_kwargs)

    def _browse_input_pdf(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Input POTS PDF",
            filetypes=[
                ("PDF files", "*.pdf"),
                ("All files", "*.*"),
            ],
        )

        if path:
            self.input_pdf_var.set(path)
            self._save_settings()

    def _browse_template_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Template Excel File",
            filetypes=[
                ("Excel files", "*.xlsx *.xlsm *.xltx *.xltm"),
                ("All files", "*.*"),
            ],
        )

        if path:
            self.template_file_var.set(path)
            self._save_settings()

    def _browse_output_dir(self) -> None:
        path = filedialog.askdirectory(
            title="Select Output Folder",
        )

        if path:
            self.output_dir_var.set(path)
            self._save_settings()

    def _toggle_target_sheet_dropdown(self) -> None:
        if self.target_sheet_dropdown_visible:
            self._hide_target_sheet_dropdown()
        else:
            self._show_target_sheet_dropdown(show_all=True)

    def _show_target_sheet_dropdown(self, show_all: bool = False) -> None:
        self._refresh_target_sheet_matches(show_all=show_all)

        self.target_sheet_dropdown.grid(
            row=5,
            column=1,
            sticky="w",
            padx=(14, 24),
            pady=(0, 8),
        )
        self.target_sheet_dropdown_visible = True

    def _hide_target_sheet_dropdown(self) -> None:
        if self.target_sheet_dropdown_visible:
            self.target_sheet_dropdown.grid_remove()
        self.target_sheet_dropdown_visible = False

    def _on_target_sheet_input_changed(self) -> None:
        if not self.target_sheet_dropdown_visible:
            self._show_target_sheet_dropdown(show_all=False)
            return

        self._refresh_target_sheet_matches(show_all=False)

    def _refresh_target_sheet_matches(self, show_all: bool = False) -> None:
        for widget in self.target_sheet_result_widgets:
            widget.destroy()

        self.target_sheet_result_widgets = []

        query = self.target_sheet_var.get().strip()
        matches = self._get_target_sheet_matches(query=query, show_all=show_all)

        if matches:
            target_height = min(
                self.TARGET_SHEET_DROPDOWN_HEIGHT,
                max(
                    self.TARGET_SHEET_NO_MATCH_HEIGHT,
                    len(matches) * (self.TARGET_SHEET_OPTION_HEIGHT + 4) + 8,
                ),
            )
            self.target_sheet_results_frame.configure(height=target_height)

            for row_index, sheet_name in enumerate(matches):
                option_button = ctk.CTkButton(
                    self.target_sheet_results_frame,
                    text=sheet_name,
                    height=self.TARGET_SHEET_OPTION_HEIGHT,
                    fg_color="transparent",
                    hover_color=self.COLOR_SECONDARY,
                    text_color=self.COLOR_TEXT,
                    corner_radius=4,
                    anchor="w",
                    command=lambda value=sheet_name: self._select_target_sheet_option(value),
                )
                option_button.grid(row=row_index, column=0, sticky="ew", padx=4, pady=2)
                self.target_sheet_result_widgets.append(option_button)

            return

        self.target_sheet_results_frame.configure(height=self.TARGET_SHEET_NO_MATCH_HEIGHT + 10)
        no_match_label = ctk.CTkLabel(
            self.target_sheet_results_frame,
            text="No predefined match.",
            height=self.TARGET_SHEET_NO_MATCH_HEIGHT,
            anchor="w",
            justify="left",
            text_color=self.COLOR_MUTED,
            font=ctk.CTkFont(size=13),
        )
        no_match_label.grid(row=0, column=0, sticky="ew", padx=8, pady=4)
        self.target_sheet_result_widgets.append(no_match_label)

    def _get_target_sheet_matches(self, query: str, show_all: bool = False) -> list[str]:
        if show_all:
            return self.TEMPLATE_SHEET_OPTIONS.copy()

        normalized_query = self._normalize_target_sheet_text(query)

        if not normalized_query:
            return self.TEMPLATE_SHEET_OPTIONS.copy()

        matches = []
        for option in self.TEMPLATE_SHEET_OPTIONS:
            normalized_option = self._normalize_target_sheet_text(option)
            if normalized_query in normalized_option:
                matches.append(option)

        return matches

    def _normalize_target_sheet_text(self, value: str) -> str:
        return str(value or "").strip().upper().replace(" ", "")

    def _select_target_sheet_option(self, sheet_name: str) -> None:
        self.target_sheet_var.set(sheet_name)
        self._hide_target_sheet_dropdown()
        self._save_settings()

    def _start_generation(self) -> None:
        try:
            request = self._build_generation_request()
        except Exception as exc:
            messagebox.showerror("Invalid Input", str(exc))
            return

        self.generation_started = True

        self._save_settings()
        self.last_output_file = None
        self.open_output_button.configure(state="disabled")
        self.generate_button.configure(state="disabled", text="Generating...")

        self._hide_target_sheet_dropdown()
        self._show_progress_area()
        self._set_progress(0, "Starting generation...")

        worker = threading.Thread(
            target=self._run_generation_worker,
            args=(request,),
            daemon=True,
        )
        worker.start()

    def _show_progress_area(self) -> None:
        self.progress_card.grid(
            row=9,
            column=0,
            columnspan=3,
            sticky="ew",
            padx=24,
            pady=(0, 24),
        )
        self.progress_card.update_idletasks()

    def _start_browser_warmup_if_idle(self) -> None:
        if self.generation_started:
            return

        if self.browser_warmup_started:
            return

        self.browser_warmup_started = True
        self.browser_warmup_running = True

        worker = threading.Thread(
            target=self._warmup_browser_worker,
            daemon=True,
        )
        worker.start()

    def _warmup_browser_worker(self) -> None:
        playwright = None
        browser = None
        context = None

        try:
            from playwright.sync_api import sync_playwright

            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(
                headless=True,
                slow_mo=0,
            )
            context = browser.new_context()
            page = context.new_page()
            page.goto("about:blank")

        except Exception:
            pass

        finally:
            try:
                if context is not None:
                    context.close()
            except Exception:
                pass

            try:
                if browser is not None:
                    browser.close()
            except Exception:
                pass

            try:
                if playwright is not None:
                    playwright.stop()
            except Exception:
                pass

            self.browser_warmup_running = False

    def _run_generation_worker(self, request: GenerationRequest) -> None:
        try:
            result = self.service.generate(
                request=request,
                status_callback=self._threadsafe_status,
            )

            self.last_output_file = result.output_file

            self.after(
                0,
                lambda: self._generation_completed(result.output_file),
            )

        except Exception as exc:
            self.after(
                0,
                lambda: self._generation_failed(exc),
            )

    def _generation_completed(self, output_file: str) -> None:
        self.generate_button.configure(state="normal", text="Generate Template")
        self.open_output_button.configure(state="normal")

        self._set_progress(100, "Completed successfully.")
        self.status_message_label.configure(text_color=self.COLOR_SUCCESS)

        messagebox.showinfo(
            "Generation Completed",
            f"Template generated successfully:\n\n{output_file}",
        )

    def _generation_failed(self, exc: Exception) -> None:
        self.generate_button.configure(state="normal", text="Generate Template")
        self.open_output_button.configure(state="disabled")

        self._set_progress(self._get_current_progress_percent(), f"Failed: {exc}")
        self.status_message_label.configure(text_color=self.COLOR_ERROR)

        messagebox.showerror(
            "Generation Failed",
            str(exc),
        )

    def _build_generation_request(self) -> GenerationRequest:
        user_name = self.user_name_var.get().strip()
        input_path = Path(self.input_pdf_var.get().strip())
        template_path = Path(self.template_file_var.get().strip())
        output_dir = Path(self.output_dir_var.get().strip())
        target_sheet_name = self.target_sheet_var.get().strip()

        if not user_name:
            raise ValueError("User Name is required.")

        if not str(input_path):
            raise ValueError("Input POTS PDF is required.")

        if not str(template_path):
            raise ValueError("Template Excel file is required.")

        if not target_sheet_name:
            raise ValueError("Target Sheet is required.")

        if not str(output_dir):
            raise ValueError("Output folder is required.")

        return GenerationRequest(
            input_path=input_path,
            template_path=template_path,
            output_dir=output_dir,
            user_name=user_name,
            show_browser=self.show_browser_var.get(),
            target_sheet_name=target_sheet_name,
        )

    def _threadsafe_status(self, message: str) -> None:
        self.after(0, lambda: self._handle_service_status(message))

    def _handle_service_status(self, message: str) -> None:
        progress, short_message = self._map_status_to_progress(message)
        self._set_progress(progress, short_message)

    def _map_status_to_progress(self, message: str) -> tuple[int, str]:
        text = str(message or "").strip()
        normalized = text.lower()

        status_steps = [
            (
                10,
                ["validating", "validate", "checking input"],
                "Checking input information...",
            ),
            (
                22,
                ["parsing", "parsed", "reading input document", "document"],
                "Reading input document...",
            ),
            (
                35,
                ["routing", "route", "identifying connection", "connection details"],
                "Identifying connection details...",
            ),
            (
                52,
                ["top thread", "upper"],
                "Retrieving top thread data...",
            ),
            (
                72,
                ["bottom thread", "lower"],
                "Retrieving bottom thread data...",
            ),
            (
                88,
                ["writing", "template", "excel", "filling"],
                "Filling Excel template...",
            ),
            (
                95,
                ["saved", "saving", "output"],
                "Saving output file...",
            ),
        ]

        for progress, keywords, display_text in status_steps:
            for keyword in keywords:
                if keyword in normalized:
                    return progress, display_text

        current_progress = self._get_current_progress_percent()
        fallback_progress = min(max(current_progress + 2, 5), 95)

        return fallback_progress, "Processing..."

    def _set_progress(self, percent: int | float, message: str) -> None:
        percent = int(max(0, min(100, percent)))

        self.progress_var.set(percent)
        self.progress_percent_var.set(f"{percent}%")

        self.progress_bar.set(percent / 100)
        self.status_message_label.configure(text=message)

        if percent < 100:
            self.status_message_label.configure(text_color=self.COLOR_MUTED)

    def _get_current_progress_percent(self) -> int:
        try:
            return int(self.progress_var.get())
        except Exception:
            return 0

    def _open_output_folder(self) -> None:
        output_dir = self.output_dir_var.get().strip()

        if self.last_output_file:
            output_dir = str(Path(self.last_output_file).parent)

        if not output_dir:
            messagebox.showwarning("No Output Folder", "No output folder is available.")
            return

        path = Path(output_dir)
        if not path.exists():
            messagebox.showwarning("Folder Not Found", f"Output folder not found:\n{path}")
            return

        os.startfile(path)

    def _load_settings(self) -> None:
        if not self.SETTINGS_PATH.exists():
            return

        try:
            with self.SETTINGS_PATH.open("r", encoding="utf-8") as f:
                settings = json.load(f)

            self.user_name_var.set(settings.get("user_name", ""))
            self.input_pdf_var.set(settings.get("input_pdf", ""))
            self.template_file_var.set(settings.get("template_file", ""))
            self.output_dir_var.set(settings.get("output_dir", ""))
            self.show_browser_var.set(bool(settings.get("show_browser", True)))

            target_sheet = str(settings.get("target_sheet") or self.TEMPLATE_SHEET_OPTIONS[0]).strip()
            if not target_sheet:
                target_sheet = self.TEMPLATE_SHEET_OPTIONS[0]
            self.target_sheet_var.set(target_sheet)

        except Exception:
            pass

    def _save_settings(self) -> None:
        try:
            self.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)

            settings = {
                "user_name": self.user_name_var.get().strip(),
                "input_pdf": self.input_pdf_var.get().strip(),
                "template_file": self.template_file_var.get().strip(),
                "target_sheet": self.target_sheet_var.get().strip(),
                "output_dir": self.output_dir_var.get().strip(),
                "show_browser": self.show_browser_var.get(),
            }

            with self.SETTINGS_PATH.open("w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False, indent=4)

        except Exception:
            pass


def main() -> None:
    app = TemplateAutomationApp()
    app.mainloop()
