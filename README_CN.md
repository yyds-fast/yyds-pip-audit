# yyds-pip-audit

`yyds-pip-audit` 是一个极速、精准的 Python 项目包导入依赖审计和 PyPI 映射工具。它能够扫描指定目录下的 Python 文件，分析代码中的 `import` 语句，自动剔除标准库与本地模块，结合本地虚拟环境包元数据，还原出实际所需的第三方 PyPI 依赖包名称及版本。

同时，它还支持与已有的 `requirements.txt` 进行对比，快速发现代码中缺失的依赖，或定位在依赖列表中多余/未使用的包。

[English README](https://github.com/yyds-fast/yyds-pip-audit/blob/main/README.md)

## ✨ 特性

- **精准解析**：使用 AST 静态解析且不会执行目标代码；超过 2 MiB 的文件会跳过并给出告警。
- **动态导入检测**：支持 `importlib.import_module()`、`__import__()` 及其别名形式的静态字符串导入。
- **智能映射**：自动扫描当前虚拟环境的包元数据，支持精准映射命名空间包（例如 `google.cloud.storage` 会被解析并精准显示为 `google.cloud.storage` 而非模糊的 `google`）。
- **本地包识别**：支持平铺布局、脚本同目录模块以及常见的 `src/` 布局，也可显式配置多个导入根目录。
- **高效遍历**：自动过滤虚拟环境、缓存、版本控制目录、构建产物和 `node_modules`。`data`、`assets` 等应用目录只有在 Git 或配置明确忽略时才跳过，避免静默漏报。
- **`.gitignore` 自动加载集成**：通过 `pathspec` 支持 Git 风格的通配、锚定、目录和否定规则。
- **配置文件配置支持**：支持从 `pyproject.toml` 的 `[tool.yyds-pip-audit]` 部分读取排除路径、输出格式及保存路径。
- **格式灵活**：支持输出为终端着色表格、标准的 `requirements.txt` 格式，或输出为易于集成的 `JSON` 格式。
- **工业级依赖对比审计**：通过 `--check` 选项对比 `requirements.txt` 审计缺失和未使用依赖。支持递归要求文件（`-r`）、可编辑模式（`-e`）、PEP 508 直接引用（`pkg @ url`）、VCS 依赖末尾的 `#egg=` 命名提取以及环境标记（`;`）过滤。
- **PEP 503 包名规范化**：依据 PyPI PEP 503 标准规范化包名比对，确保匹配万无一失。
- **CI 门禁**：可通过 `--fail-on` 在发现缺失或未检测到直接引用的依赖时返回非零退出码。
- **安全导出**：无法验证的 import/PyPI 同名猜测默认不会写入 requirements，需显式确认后导出。
- **无感适配**：全面兼容 Python 3.10+ 及主流操作系统。

## 🚀 安装

可以通过 `pip` 直接从本地或 PyPI 安装：

```bash
# 本地开发模式安装
pip install -e .

# 直接安装
pip install -U yyds-pip-audit
```

## 🛠 使用方法

安装完成后，可以在终端中使用 `yyds-pip-audit` 或 `yyds_pip_audit` 命令行工具。
也可以使用 `python -m yyds_pip_audit` 运行。

### 1. 基础扫描

在项目根目录下直接运行：

```bash
yyds-pip-audit
```

或者指定扫描的目标文件夹路径：

```bash
yyds-pip-audit /path/to/project
```

### 2. 导出依赖项

支持将扫描到的依赖项以不同格式导出到文件：

```bash
# 导出为标准的 requirements.txt 文件
yyds-pip-audit -f requirements -o requirements.txt

# 导出为 JSON 格式文件
yyds-pip-audit -f json -o deps.json
```

### 3. 依赖文件对比审计 (Check)

对比已有的 `requirements.txt`，检查是否存在代码里导入了但依赖文件未记录（缺失），或者依赖文件里有但代码里未实际导入（未使用）的情况：

```bash
yyds-pip-audit --check requirements.txt

# 缺少依赖时让 CI 失败
yyds-pip-audit --check requirements.txt --fail-on missing
```

### 4. 忽略特定目录

可以通过 `-e` 或 `--exclude` 忽略不想扫描的自定义文件夹。支持多次指定、逗号分隔、以及指定相对路径：

```bash
# 忽略多个目录
yyds-pip-audit -e my_temp_dir -e tests/mock_data

# 使用逗号分隔一次性忽略多个目录
yyds-pip-audit -e my_temp_dir,build_assets

# 忽略指定的相对路径目录（精确排除）
yyds-pip-audit -e src/data
```

非标准包布局可显式指定导入根目录：

```bash
yyds-pip-audit --source-root backend/src --source-root packages/shared
```

### 5. 配置文件 pyproject.toml 配置

你可以直接在项目的 `pyproject.toml` 文件的 `[tool.yyds-pip-audit]` 节点下进行全局配置，例如：

```toml
[tool.yyds-pip-audit]
exclude = ["build_assets", "custom_dir"]
source_roots = ["src"]
format = "json"
output = "audit_report.json"
fail_on = "missing"
evaluate_markers = true
```

命令行指定的参数永远会覆盖配置文件中的默认配置。
配置文件中的输出路径以项目目录为基准，并且不能写到项目目录之外。

## 📋 命令行参数详解

```
Usage: yyds-pip-audit [OPTIONS] [DIRECTORY]

  yyds-pip-audit: 极速且精准的 Python 项目导入依赖审计及 PyPI 包映射工具。

Options:
  -o, --output PATH               将依赖输出保存到指定文件 (例如 requirements.txt)
  -f, --format [text|requirements|json]
                                  依赖输出的格式: text (终端表格), requirements (标准依赖), json (JSON 数据) [default: text]
  -e, --exclude TEXT              要忽略的额外目录名称 (可多次指定)
  --source-root TEXT              用于识别本地包的项目导入根目录
  -c, --check PATH                审计对比指定的 requirements 文件，分析缺失和多余依赖
  --fail-on [none|missing|unused|any]
                                  对指定的审计问题返回退出码 1
  --include-unresolved / --skip-unresolved
                                  包含或跳过未经验证的包名猜测
  --evaluate-markers / --ignore-markers
                                  选择是否按当前解释器计算环境标记
  --version                       显示版本并退出。
  --help                          显示此帮助信息并退出。
```

## 💡 映射原理说明

很多 PyPI 库的安装名称与其在 Python 代码中 import 的名称并不一致，例如：
- `import cv2` -> `opencv-python`
- `import PIL` -> `Pillow`
- `import yaml` -> `PyYAML`
- `import fitz` -> `PyMuPDF`

`yyds-pip-audit` 通过以下两阶段方案解决此映射痛点：
1. **本地环境元数据映射**：读取当前 Python 运行环境中所有分发包的 `top_level.txt` 文件，流式构建反向映射关系。
2. **硬编码兜底配置**：针对未安装在本地或没有提供 `top_level.txt` 的常规坑包进行静态映射字典匹配。

每条结果都会包含 `metadata`、`fallback` 或 `unresolved` 三种 `resolution` 状态。
`unresolved` 默认不会作为可安装依赖导出，确认后可使用 `--include-unresolved`。

## 开发与构建

```bash
pip install -e ".[test,build,lint]"
pytest --cov --cov-report=term-missing
ruff check yyds_pip_audit tests
./build.sh                 # 构建并校验，不上传
./build.sh --upload        # 显式上传 PyPI
```

## 📄 开源协议

本项目采用 [MIT](https://github.com/yyds-fast/yyds-pip-audit/blob/main/LICENSE) 协议。
