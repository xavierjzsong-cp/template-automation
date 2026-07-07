param(
    [switch]$SkipInstall,
    [switch]$SkipSmokeTest
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Assert-PathExists {
    param(
        [string]$Path,
        [string]$Description
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Description not found: $Path"
    }
}

function Remove-WorkspaceDirectory {
    param([string]$RelativePath)

    $workspace = (Resolve-Path -LiteralPath ".").Path
    $resolved = Resolve-Path -LiteralPath $RelativePath -ErrorAction SilentlyContinue

    if (-not $resolved) {
        return
    }

    $target = $resolved.Path
    if (-not $target.StartsWith($workspace, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove outside workspace: $target"
    }

    Remove-Item -LiteralPath $target -Recurse -Force
}

Write-Step "Checking project root"
Assert-PathExists "run_ui.py" "Application entrypoint"
Assert-PathExists "TemplateAutomationTool.spec" "PyInstaller spec"
Assert-PathExists "requirements.txt" "Requirements file"
Assert-PathExists "config\partners.yaml" "Partner config"
Assert-PathExists "config\field_mapping.yaml" "Field mapping config"
Assert-PathExists "packaging\pyinstaller_runtime_hook.py" "PyInstaller runtime hook"

$python = ".\py314\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        throw "Python not found. Expected .\py314\Scripts\python.exe or python on PATH."
    }
    $python = $pythonCommand.Source
}

Write-Host "Using Python: $python"

if (-not $SkipInstall) {
    Write-Step "Installing Python dependencies"
    & $python -m pip install -r requirements.txt

    Write-Step "Installing Playwright Chromium"
    & $python -m playwright install chromium
}
else {
    Write-Step "Skipping dependency install"
}

Write-Step "Running compile check"
& $python -m compileall -q run_ui.py src

Write-Step "Running import/config check"
& $python -c "from src.ui.app import TemplateAutomationApp; from src.services.template_generation_service import TemplateGenerationService; import yaml; from pathlib import Path; yaml.safe_load(Path('config/partners.yaml').read_text(encoding='utf-8')); print('checks ok')"

Write-Step "Checking Playwright browser cache"
$localAppData = [Environment]::GetEnvironmentVariable("LOCALAPPDATA")
if (-not $localAppData) {
    throw "LOCALAPPDATA is not set. Cannot locate ms-playwright browser cache."
}

$playwrightBrowsers = Join-Path $localAppData "ms-playwright"
Assert-PathExists $playwrightBrowsers "Playwright browser cache"

Write-Step "Cleaning previous build outputs"
Remove-WorkspaceDirectory "build"
Remove-WorkspaceDirectory "dist"

Write-Step "Building executable with PyInstaller"
& $python -m PyInstaller TemplateAutomationTool.spec --noconfirm --clean

$distRoot = "dist\TemplateAutomationTool"
$exePath = Join-Path $distRoot "TemplateAutomationTool.exe"
$partnersPath = Join-Path $distRoot "_internal\config\partners.yaml"
$fieldMappingPath = Join-Path $distRoot "_internal\config\field_mapping.yaml"
$bundledBrowsers = Join-Path $distRoot "_internal\ms-playwright"

Write-Step "Validating dist contents"
Assert-PathExists $exePath "Executable"
Assert-PathExists $partnersPath "Bundled partners.yaml"
Assert-PathExists $fieldMappingPath "Bundled field_mapping.yaml"
Assert-PathExists $bundledBrowsers "Bundled Playwright browser folder"

$chrome = Get-ChildItem -LiteralPath $bundledBrowsers -Recurse -Filter chrome.exe -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $chrome) {
    throw "Bundled Chromium chrome.exe not found under $bundledBrowsers"
}

if (-not $SkipSmokeTest) {
    Write-Step "Running non-source startup smoke test"
    $testDir = Join-Path $env:TEMP ("TemplateAutomationTool_dist_test_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
    Copy-Item -LiteralPath $distRoot -Destination $testDir -Recurse -Force

    $testExe = Join-Path $testDir "TemplateAutomationTool.exe"
    $process = Start-Process -FilePath $testExe -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 8

    if ($process.HasExited) {
        throw "Smoke test failed. Exe exited early with code $($process.ExitCode). Test dir: $testDir"
    }

    Stop-Process -Id $process.Id -Force
    Write-Host "Smoke test passed. Test dir: $testDir"
}
else {
    Write-Step "Skipping startup smoke test"
}

Write-Step "Creating release zip"
$zipPath = "dist\TemplateAutomationTool.zip"
Compress-Archive -LiteralPath $distRoot -DestinationPath $zipPath -Force
Assert-PathExists $zipPath "Release zip"

$zipItem = Get-Item -LiteralPath $zipPath
Write-Host ""
Write-Host "Build completed successfully." -ForegroundColor Green
Write-Host ("Zip: {0}" -f $zipItem.FullName)
Write-Host ("Size: {0:N2} MB" -f ($zipItem.Length / 1MB))
