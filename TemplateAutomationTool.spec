# -*- mode: python ; coding: utf-8 -*-

from __future__ import annotations

import os
from pathlib import Path


project_root = Path(SPECPATH)
local_appdata = os.environ.get("LOCALAPPDATA", "")
playwright_browsers = Path(
    os.environ.get(
        "PLAYWRIGHT_BROWSERS_PATH",
        str(Path(local_appdata) / "ms-playwright") if local_appdata else "",
    )
)


def collect_tree(source: Path, dest: str) -> list[tuple[str, str]]:
    if not source.exists():
        raise FileNotFoundError(f"Required data folder not found: {source}")

    files: list[tuple[str, str]] = []
    for path in source.rglob("*"):
        if path.is_file():
            relative_parent = path.relative_to(source).parent
            files.append((str(path), str(Path(dest) / relative_parent)))
    return files


datas = [
    (str(project_root / "config" / "partners.yaml"), "config"),
    (str(project_root / "config" / "field_mapping.yaml"), "config"),
]
datas += collect_tree(playwright_browsers, "ms-playwright")


a = Analysis(
    ["run_ui.py"],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(project_root / "packaging" / "pyinstaller_runtime_hook.py")],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TemplateAutomationTool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="TemplateAutomationTool",
)
