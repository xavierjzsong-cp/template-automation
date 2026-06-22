# Template Automation Tool

A Windows desktop automation tool that reads a POTS PDF, determines the top and bottom connection partners, retrieves connection datasheet / blanking dimension data from partner websites, and writes the final result into a selected Excel template sheet.

中文说明: [README-CN.md](README-CN.md)

## Audience

- Internal end users: download the packaged release zip, extract it, and run the exe.
- Developers / maintainers / release builders: clone the Git repository, modify, test, package, and publish new releases.

## How End Users Download the Latest Version

End users do not need Python or the source code.

1. Open the GitHub repository page.
2. Go to **Releases**.
3. Find the latest release.
4. Download `TemplateAutomationTool.zip`.
5. Extract the full zip file.
6. Double-click `TemplateAutomationTool.exe`.

Do not copy only the exe. The whole extracted folder must stay together because the exe depends on the bundled `_internal` folder, configuration files, Python runtime, and Playwright Chromium.

## What Is a GitHub Release?

A GitHub Release is a versioned download page for packaged deliverables. The Git repository should store source code and packaging configuration. It should not store large packaged exe zip files. After each version update, maintainers should:

1. Build from the latest `main` branch.
2. Generate `dist/TemplateAutomationTool.zip`.
3. Create a new GitHub Release.
4. Upload the zip as a release asset.
5. Ask internal users to download the latest release.

## Project Structure

```text
run_ui.py
    GUI entry point.

src/ui/app.py
    CustomTkinter desktop UI.

src/services/template_generation_service.py
    Main orchestration service connecting parser / router / mapper / adapter / writer.

src/parsers/pots_doc_parser.py
    POTS PDF parser.

src/routers/partner_router.py
    Routes top / bottom connections to partners.

src/mappers/
    Partner input mappers and coating mapper.

src/adapters/
    Playwright automation for VAM / TSH / JFE / HT websites.

src/writers/template_writer.py
    Excel template writer.

config/partners.yaml
    Partner URL and capability configuration. Bundled with the exe.

TemplateAutomationTool.spec
    PyInstaller onedir packaging configuration.

packaging/pyinstaller_runtime_hook.py
    PyInstaller runtime hook for bundled Playwright browsers.
```

## User Data and Paths

At runtime, the app creates user-specific data under:

```text
%LOCALAPPDATA%\TemplateAutomationTool\
```

Files include:

```text
%LOCALAPPDATA%\TemplateAutomationTool\config\ui_settings.json
    Stores the user's recently selected PDF, template, output folder, etc.

%LOCALAPPDATA%\TemplateAutomationTool\logs\
    Stores adapter runtime logs.
```

These files should not be committed to Git and should not be bundled as fixed files in the exe package. Each user gets their own local files.

## Development Setup

Install dependencies:

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
```

If using the current project virtual environment:

```powershell
.\py314\Scripts\python.exe -m pip install -r requirements.txt
.\py314\Scripts\python.exe -m playwright install chromium
```

## Run from Source

```powershell
python run_ui.py
```

Or:

```powershell
.\py314\Scripts\python.exe run_ui.py
```

## Package the Exe

The current packaging strategy uses PyInstaller `onedir`. Do not start with `onefile`; Playwright + Chromium is more stable and easier to debug in onedir.

Build command:

```powershell
.\py314\Scripts\python.exe -m PyInstaller TemplateAutomationTool.spec --noconfirm --clean
```

Build output:

```text
dist/TemplateAutomationTool/
```

Create the user-facing zip:

```powershell
Compress-Archive -LiteralPath dist\TemplateAutomationTool -DestinationPath dist\TemplateAutomationTool.zip -Force
```

## What Is build_exe.ps1?

`build_exe.ps1` would be a future one-click packaging script. It is not business logic. It would simply collect the packaging commands in one PowerShell script, such as installing Playwright Chromium, running PyInstaller, and creating the final zip.

This script has not been created yet. For now, use the manual commands above.

## Git Rules

Commit:

```text
src/
config/partners.yaml
config/field_mapping.yaml
requirements.txt
TemplateAutomationTool.spec
packaging/
README.md
README-CN.md
```

## Suggested Release Flow

1. Make sure `main` is up to date.
2. Run smoke tests or at least verify parser/router/service behavior.
3. Build with PyInstaller.
4. Copy `dist/TemplateAutomationTool/` to a non-source folder and start the exe.
5. Zip `dist/TemplateAutomationTool`.
6. Upload the zip to a GitHub Release.
7. Ask internal users to download the latest release.
