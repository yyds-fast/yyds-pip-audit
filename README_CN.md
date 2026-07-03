# yyds-pip-audit

`yyds-pip-audit` 是一个极速、精准的 Python 项目包导入依赖审计和 PyPI 映射工具。它能够扫描指定目录下的 Python 文件，分析代码中的 `import` 语句，自动剔除标准库与本地模块，结合本地虚拟环境包元数据，还原出实际所需的第三方 PyPI 依赖包名称及版本。

同时，它还支持与已有的 `requirements.txt` 进行对比，快速发现代码中缺失的依赖，或定位在依赖列表中多余/未使用的包。

[English README](README.md)

## ✨ 特性

- **精准解析**：使用 AST 静态解析，准确抓取 top-level 导入（包含 `import xxx` 和 `from xxx import yyy`）。对于超过 2MB 的超大生成文件自动跳过以提升性能。
- **智能映射**：自动扫描当前虚拟环境的包元数据，支持精准映射命名空间包（例如 `google.cloud.storage` 会被解析并精准显示为 `google.cloud.storage` 而非模糊的 `google`）。
- **防止虚拟环境与大目录污染**：在扫描项目时自动过滤 `.venv`、`venv`、`node_modules` 等开发环境目录，并默认过滤 `data`、`static`、`media`、`assets`、`public`、`uploads`、`logs`、`tmp`、`temp`、`htmlcov` 等非代码/资源目录，杜绝扫描卡顿。
- **格式灵活**：支持输出为精美终端表格、标准 `requirements.txt` 格式，或输出为易于程序解析的 `JSON` 格式。
- **多维度审计**：通过 `--check` 选项审计已有依赖文件，清晰列出“缺失的依赖”与“未使用的依赖”。
- **无感适配**：全面兼容 Python 3.7+ 及所有主流操作系统。

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

## 📋 命令行参数详解

```
Usage: yyds-pip-audit [OPTIONS] [DIRECTORY]

  yyds-pip-audit: 极速且精准的 Python 项目导入依赖审计及 PyPI 包映射工具。

Options:
  -o, --output PATH               将依赖输出保存到指定文件 (例如 requirements.txt)
  -f, --format [text|requirements|json]
                                  依赖输出的格式: text (终端表格), requirements (标准依赖), json (JSON 数据) [default: text]
  -e, --exclude TEXT              要忽略的额外目录名称 (可多次指定)
  -c, --check PATH                审计对比指定的 requirements 文件，分析缺失和多余依赖
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

## 📄 开源协议

本项目采用 [MIT](LICENSE) 协议。
