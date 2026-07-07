# Template Automation Tool

Windows 桌面自动化工具，用于从 POTS PDF 中提取连接信息，访问 partner 网站获取 connection datasheet / blanking dimensions，并将结果写入指定 Excel template sheet。

English version: [README.md](README.md)

## 适用人群

- 内部普通用户：下载已打包的 release zip，解压后双击 exe 使用。
- 开发 / 维护 / 打包人员：从 Git 仓库获取源码，修改、测试并重新打包发布。

## 普通用户如何下载最新版

普通用户不需要安装 Python，也不需要下载源码。

1. 打开 GitHub 仓库页面。
2. 进入右侧或顶部的 **Releases** 页面。
3. 找到最新版本。
4. 下载 `TemplateAutomationTool.zip`。
5. 解压整个 zip。
6. 双击 `TemplateAutomationTool.exe`。

注意：不要只复制 exe。必须保留整个解压后的文件夹，因为 exe 依赖 `_internal` 目录中的 Python runtime、配置文件和 Playwright Chromium。

## GitHub Release 是什么

GitHub Release 是 GitHub 提供的“版本发布页面”。每次版本更新后，维护人员应：

1. 从最新 `main` 分支打包。
2. 生成 `dist/TemplateAutomationTool.zip`。
3. 在 GitHub 创建新的 Release。
4. 上传 zip 到 Release assets。
5. 通知内部用户下载最新 Release。

## 项目结构

```text
run_ui.py
    GUI 入口。

src/ui/app.py
    CustomTkinter 桌面界面。

src/services/template_generation_service.py
    核心编排流程，串联 parser / router / mapper / adapter / writer。

src/parsers/pots_doc_parser.py
    POTS PDF 解析。

src/routers/partner_router.py
    根据 top / bottom connection 判断 partner。

src/mappers/
    partner 输入映射与 coating 映射。

src/adapters/
    Playwright 网页自动化，访问 VAM / TSH / JFE / HT 网站。

src/writers/template_writer.py
    写入 Excel template。

config/partners.yaml
    partner URL 和能力配置，打包时随 exe 一起发布。

TemplateAutomationTool.spec
    PyInstaller onedir 打包配置。

packaging/pyinstaller_runtime_hook.py
    PyInstaller runtime hook，用于让 exe 使用随包发布的 Playwright browser。
```

## 用户数据与路径

程序运行时会在用户电脑上创建自己的数据目录：

```text
%LOCALAPPDATA%\TemplateAutomationTool\
```

其中：

```text
%LOCALAPPDATA%\TemplateAutomationTool\config\ui_settings.json
    保存用户最近选择的 PDF、template、output folder 等。

%LOCALAPPDATA%\TemplateAutomationTool\logs\
    保存 adapter 运行日志。
```

这些文件不应提交到 Git，也不应随 exe 固定打包。每个用户电脑都会自动生成自己的文件。

## 开发环境准备

建议使用项目内虚拟环境或本地虚拟环境。安装依赖：

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
```

如果使用当前项目虚拟环境：

```powershell
.\py314\Scripts\python.exe -m pip install -r requirements.txt
.\py314\Scripts\python.exe -m playwright install chromium
```

## 本地运行源码版

```powershell
python run_ui.py
```

或：

```powershell
.\py314\Scripts\python.exe run_ui.py
```

## 打包 exe

当前使用 PyInstaller `--onedir` 方案。不要优先使用 `--onefile`，因为 Playwright + Chromium 在 onedir 下更稳定，也更方便排查路径问题。

推荐使用本地一键打包脚本：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_exe.ps1
```

常用选项：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_exe.ps1 -SkipInstall
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_exe.ps1 -SkipInstall -SkipSmokeTest
```

该脚本会安装/检查依赖、验证项目、运行 PyInstaller、检查打包文件、从非源码目录启动 exe 做 smoke test，并生成 `dist/TemplateAutomationTool.zip`。

手动打包命令：

打包命令：

```powershell
.\py314\Scripts\python.exe -m PyInstaller TemplateAutomationTool.spec --noconfirm --clean
```

打包完成后输出：

```text
dist/TemplateAutomationTool/
```

压缩给用户：

```powershell
Compress-Archive -LiteralPath dist\TemplateAutomationTool -DestinationPath dist\TemplateAutomationTool.zip -Force
```

## build_exe.ps1 是什么

`build_exe.ps1` 是本地一键打包脚本。它不是业务代码，而是把安装浏览器、运行 PyInstaller、检查打包文件、启动 smoke test、压缩 zip 等命令集中到一个 PowerShell 脚本里，减少每次手动打包出错的概率。

正常本地打包建议使用该脚本。上面的手动命令主要用于排查问题。

## CI/CD

仓库中包含 GitHub Actions workflows：

```text
.github/workflows/ci.yml
    CI 检查，用于 push、pull request 和手动运行。

.github/workflows/release.yml
    手动触发的 CD 流程，用于打包 exe zip 并上传到 GitHub Release。
```

CI workflow 会检查 Python 编译、核心模块 import、Playwright 安装和 YAML 配置。它不会发布 Release。

Release workflow 需要在 GitHub Actions 页面手动触发。输入版本号，例如 `v1.0.1`，它会构建 `dist/TemplateAutomationTool.zip` 并上传为 GitHub Release asset。

## Git 提交规则

应提交：

```text
src/
config/partners.yaml
config/field_mapping.yaml
requirements.txt
TemplateAutomationTool.spec
packaging/
build_exe.ps1
.github/workflows/
README.md
README-CN.md
```

## 发布流程建议

1. 确认 `main` 分支代码最新。
2. 运行 smoke test 或至少确认 parser/router/service 可用。
3. 本地运行 `.\build_exe.ps1`，或在 GitHub Actions 手动运行 Release workflow。
4. 上传或确认 GitHub Release 中的 `TemplateAutomationTool.zip`。
7. 通知内部用户下载最新版 Release。
