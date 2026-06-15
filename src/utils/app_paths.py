from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "TemplateAutomationTool"


def source_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def bundle_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)

    return source_project_root()


def resource_path(*parts: str) -> Path:
    return bundle_root().joinpath(*parts)


def user_data_dir() -> Path:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / APP_NAME

    return Path.home() / ".local" / "share" / APP_NAME


def settings_path() -> Path:
    return user_data_dir() / "config" / "ui_settings.json"


def logs_dir() -> Path:
    return user_data_dir() / "logs"
