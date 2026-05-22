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


class TemplateAutomationApp(ctk.CTk):

    SETTINGS_PATH = Path("config") / "ui_settings.json"

    def __init__(self) -> None:
        super().__init__()

        self.title("Template Automation Tool")
        self.geometry("820x620")
        self.minsize(760, 560)

        ctk.set_appearance_mode("Light")
        ctk.set_default_color_theme("blue")

        self.service = TemplateGenerationService()
        self.last_output_file: str | None = None

        self.user_name_var = ctk.StringVar()
        self.input_pdf_var = ctk.StringVar()
        self.template_file_var = ctk.StringVar()
        self.output_dir_var = ctk.StringVar()
        self.show_browser_var = ctk.BooleanVar(value=True)

        self._load_settings()
        self._build_ui()

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")

        title = ctk.CTkLabel(
            header,
            text="Template Automation Tool",
            font=ctk.CTkFont(size=24, weight="bold"),
        )
        title.pack(anchor="w", padx=24, pady=(18, 4))

        subtitle = ctk.CTkLabel(
            header,
            text="Select input files, template file, and output folder to generate the completed template.",
            font=ctk.CTkFont(size=13),
        )
        subtitle.pack(anchor="w", padx=24, pady=(0, 18))

        main = ctk.CTkFrame(self)
        main.grid(row=1, column=0, sticky="nsew", padx=24, pady=20)
        main.grid_columnconfigure(1, weight=1)
        main.grid_rowconfigure(6, weight=1)

        self._add_label(main, "User Name", row=0)
        user_entry = ctk.CTkEntry(main, textvariable=self.user_name_var)
        user_entry.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(12, 0), pady=8)

        self._add_label(main, "Input POTS PDF", row=1)
        input_entry = ctk.CTkEntry(main, textvariable=self.input_pdf_var)
        input_entry.grid(row=1, column=1, sticky="ew", padx=(12, 8), pady=8)
        input_button = ctk.CTkButton(
            main,
            text="Browse",
            width=110,
            command=self._browse_input_pdf,
        )
        input_button.grid(row=1, column=2, sticky="e", pady=8)

        self._add_label(main, "Template Excel File", row=2)
        template_entry = ctk.CTkEntry(main, textvariable=self.template_file_var)
        template_entry.grid(row=2, column=1, sticky="ew", padx=(12, 8), pady=8)
        template_button = ctk.CTkButton(
            main,
            text="Browse",
            width=110,
            command=self._browse_template_file,
        )
        template_button.grid(row=2, column=2, sticky="e", pady=8)

        self._add_label(main, "Output Folder", row=3)
        output_entry = ctk.CTkEntry(main, textvariable=self.output_dir_var)
        output_entry.grid(row=3, column=1, sticky="ew", padx=(12, 8), pady=8)
        output_button = ctk.CTkButton(
            main,
            text="Browse",
            width=110,
            command=self._browse_output_dir,
        )
        output_button.grid(row=3, column=2, sticky="e", pady=8)

        options_frame = ctk.CTkFrame(main, fg_color="transparent")
        options_frame.grid(row=4, column=1, columnspan=2, sticky="w", padx=(12, 0), pady=8)

        show_browser_checkbox = ctk.CTkCheckBox(
            options_frame,
            text="Show browser during automation",
            variable=self.show_browser_var,
        )
        show_browser_checkbox.pack(anchor="w")

        button_frame = ctk.CTkFrame(main, fg_color="transparent")
        button_frame.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(18, 12))
        button_frame.grid_columnconfigure(0, weight=1)

        self.generate_button = ctk.CTkButton(
            button_frame,
            text="Generate Template",
            height=40,
            command=self._start_generation,
        )
        self.generate_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.open_output_button = ctk.CTkButton(
            button_frame,
            text="Open Output Folder",
            height=40,
            width=160,
            state="disabled",
            command=self._open_output_folder,
        )
        self.open_output_button.grid(row=0, column=1, sticky="e")

        status_label = ctk.CTkLabel(
            main,
            text="Status",
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        status_label.grid(row=6, column=0, sticky="nw", pady=(8, 0))

        self.status_textbox = ctk.CTkTextbox(main, height=190)
        self.status_textbox.grid(
            row=6,
            column=1,
            columnspan=2,
            sticky="nsew",
            padx=(12, 0),
            pady=(8, 0),
        )
        self._append_status("Ready.")

    def _add_label(self, parent, text: str, row: int) -> None:
        label = ctk.CTkLabel(
            parent,
            text=text,
            anchor="w",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        label.grid(row=row, column=0, sticky="w", pady=8)

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

    def _start_generation(self) -> None:
        try:
            request = self._build_generation_request()
        except Exception as exc:
            messagebox.showerror("Invalid Input", str(exc))
            return

        self._save_settings()
        self.last_output_file = None
        self.open_output_button.configure(state="disabled")
        self.generate_button.configure(state="disabled", text="Generating...")

        self._append_status("")
        self._append_status("Starting generation...")

        worker = threading.Thread(
            target=self._run_generation_worker,
            args=(request,),
            daemon=True,
        )
        worker.start()

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

        self._append_status(f"Success. Output file: {output_file}")
        messagebox.showinfo(
            "Generation Completed",
            f"Template generated successfully:\n\n{output_file}",
        )

    def _generation_failed(self, exc: Exception) -> None:
        self.generate_button.configure(state="normal", text="Generate Template")
        self.open_output_button.configure(state="disabled")

        self._append_status(f"Failed: {exc}")
        messagebox.showerror(
            "Generation Failed",
            str(exc),
        )

    def _build_generation_request(self) -> GenerationRequest:
        user_name = self.user_name_var.get().strip()
        input_path = Path(self.input_pdf_var.get().strip())
        template_path = Path(self.template_file_var.get().strip())
        output_dir = Path(self.output_dir_var.get().strip())

        if not user_name:
            raise ValueError("User Name is required.")

        if not str(input_path):
            raise ValueError("Input POTS PDF is required.")

        if not str(template_path):
            raise ValueError("Template Excel file is required.")

        if not str(output_dir):
            raise ValueError("Output folder is required.")

        return GenerationRequest(
            input_path=input_path,
            template_path=template_path,
            output_dir=output_dir,
            user_name=user_name,
            show_browser=self.show_browser_var.get(),
        )

    def _append_status(self, message: str) -> None:
        self.status_textbox.insert("end", message + "\n")
        self.status_textbox.see("end")

    def _threadsafe_status(self, message: str) -> None:
        self.after(0, lambda: self._append_status(message))

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

        except Exception:
            pass

    def _save_settings(self) -> None:
        try:
            self.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)

            settings = {
                "user_name": self.user_name_var.get().strip(),
                "input_pdf": self.input_pdf_var.get().strip(),
                "template_file": self.template_file_var.get().strip(),
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