# yyds-pip-audit

`yyds-pip-audit` is a fast and precise CLI tool/library designed to audit Python package imports and map them to their corresponding PyPI distribution names and versions. It extracts `import` statements from source codes, filters out standard libraries and local project modules, and utilizes local Python environment package metadata to trace PyPI names.

It also supports checking your code imports against an existing `requirements.txt` to help you identify missing dependencies or unused packages.

## ✨ Features

- **AST Parsing**: Statically parses `.py` files using the Python Abstract Syntax Tree (AST) to reliably find all top-level imports.
- **Smart PyPI Mapping**: Scans package metadata (`top_level.txt`) in your active python environment to map import names like `cv2` to `opencv-python`, `PIL` to `Pillow`, etc.
- **Clean Walk**: Automatically ignores directories like `.venv`, `venv`, `node_modules`, `.git`, `.idea` etc., preventing environment pollution.
- **Multiple Formats**: Outputs audit results as a beautiful terminal table, standard `requirements.txt` format, or `JSON` format.
- **Dependency Checking**: Offers a `--check` flag to scan and compare against a requirements file, revealing missing and unused dependencies.
- **Wide Compatibility**: Compatible with Python 3.7+ across all platforms.

## 🚀 Installation

Install it using `pip` locally or from PyPI:

```bash
# Install in editable/development mode
pip install -e .

# Normal installation
pip install yyds-pip-audit
```

## 🛠 Usage

Once installed, you can use the `yyds-pip-audit` or `yyds_pip_audit` command.

### 1. Basic Audit

Run it in your project's root folder:

```bash
yyds-pip-audit
```

Or target a specific directory:

```bash
yyds-pip-audit /path/to/project
```

### 2. Export Dependencies

Save audited dependencies in different file formats:

```bash
# Save to standard requirements.txt format
yyds-pip-audit -f requirements -o requirements.txt

# Save to JSON format
yyds-pip-audit -f json -o dependencies.json
```

### 3. Check Against Requirements File

Check if the codebase imports any package not registered in requirements, or if the requirements file has packages never imported:

```bash
yyds-pip-audit --check requirements.txt
```

### 4. Custom Exclude Folders

Use `-e` or `--exclude` to ignore additional folders:

```bash
yyds-pip-audit -e temp_folder -e tests/mocks
```

## 📋 Command Line Interface

```
Usage: yyds-pip-audit [OPTIONS] [DIRECTORY]

  yyds-pip-audit: A robust Python package import dependency auditor and PyPI mapper.

Options:
  -o, --output PATH               Save dependencies output to target file (e.g. requirements.txt)
  -f, --format [text|requirements|json]
                                  Output format: text (colored table), requirements (standard), json (JSON data) [default: text]
  -e, --exclude TEXT              Extra directory names to exclude (can be specified multiple times)
  -c, --check PATH                Compare against an existing requirements file to detect missing or unused packages
  --version                       Show the version and exit.
  --help                          Show this message and exit.
```

## 💡 How the Mapping Works

Many PyPI packages use import names that differ from their PyPI name, e.g.:
- `import cv2` -> `opencv-python`
- `import PIL` -> `Pillow`
- `import yaml` -> `PyYAML`
- `import fitz` -> `PyMuPDF`

`yyds-pip-audit` resolves this mapping in two ways:
1. **Local Metadata Scanning**: Traverses installed libraries in the current Python environment and parses their metadata (`top_level.txt`).
2. **Hardcoded Fallbacks**: Includes a default mapping mapping for common packages that might not be installed or don't declare `top_level.txt`.

## 📄 License

This project is licensed under the [MIT](LICENSE) License.
