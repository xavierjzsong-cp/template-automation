from __future__ import annotations

import os
import sys
from pathlib import Path


def _bundle_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)

    return Path(sys.executable).resolve().parent


bundled_browsers = _bundle_root() / "ms-playwright"
if bundled_browsers.exists():
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundled_browsers)
