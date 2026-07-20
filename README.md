# yyds-pip-audit

`yyds-pip-audit` is a fast and precise CLI tool/library designed to audit Python package imports and map them to their corresponding PyPI distribution names and versions. It extracts `import` statements from source codes, filters out standard libraries and local project modules, and utilizes local Python environment package metadata to trace PyPI names.

It also supports checking your code imports against an existing `requirements.txt` to help you identify missing dependencies or unused packages.

[中文说明 (Chinese README)](https://github.com/yyds-fast/yyds-pip-audit/blob/main/README_CN.md)

## ✨ Features

- **AST Parsing**: Statically parses `.py` files using the Python Abstract Syntax Tree (AST) without executing target code. Files larger than 2 MiB are skipped with a warning.
- **Dynamic Import Scanning**: Detects static string imports through `importlib.import_module()`, `__import__()`, and aliased import helpers.
- **Smart PyPI Mapping**: Scans package metadata in your active python environment. Supports precise mapping of namespace packages (e.g. `google.cloud.storage` maps to `google-cloud-storage` and is displayed as such under `Import Name` instead of a vague `google`).
- **Local Package Detection**: Understands flat projects, script-local modules, and the common `src/` package layout. Additional import roots can be configured explicitly.
- **Clean Walk**: Automatically ignores virtual environments, caches, VCS metadata, build artifacts, and `node_modules`. Application directories such as `data` or `assets` are scanned unless ignored by Git or configuration, preventing silent dependency omissions.
- **Auto `.gitignore` Integration**: Uses Git-compatible wildmatch, anchoring, directory, and negation rules through `pathspec`.
- **`pyproject.toml` Support**: Reads configuration settings from `[tool.yyds-pip-audit]` section in `pyproject.toml`.
- **Multiple Formats**: Outputs audit results as a beautiful terminal table, standard `requirements.txt` format, or `JSON` format.
- **Industrial Requirements Checking**: Offers a `--check` flag to scan and compare against a requirements file, revealing missing and unused dependencies. Supports recursive requirements (`-r`), editable requirements (`-e`), PEP 508 direct references (`requests @ https://...`), egg fragments in Git/VCS URLs (`#egg=name`), and environment markers.
- **PEP 503 Normalization**: Adheres to PyPI standard normalization for package names comparison.
- **CI-friendly Checks**: `--fail-on` can turn missing or unreferenced dependency findings into a non-zero process exit code.
- **Safe Requirements Export**: Unresolved import-to-package guesses are reported but excluded from requirements output unless explicitly enabled.
- **Wide Compatibility**: Compatible with Python 3.10+ across all major platforms.

## 🚀 Installation

Install it using `pip` locally or from PyPI:

```bash
# Install in editable/development mode
pip install -e .

# Normal installation
pip install -U yyds-pip-audit
```

## 🛠 Usage

Once installed, you can use the `yyds-pip-audit` or `yyds_pip_audit` command.
It can also be run as `python -m yyds_pip_audit`.

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

# Fail CI when imported packages are missing from requirements
yyds-pip-audit --check requirements.txt --fail-on missing
```

### 4. Custom Exclude Folders

Use `-e` or `--exclude` to ignore additional folders. You can pass multiple options, use comma-separated paths, or specify relative paths:

```bash
# Exclude multiple folders
yyds-pip-audit -e temp_folder -e tests/mocks

# Exclude via comma-separated list
yyds-pip-audit -e temp_folder,build_assets

# Exclude specific relative path
yyds-pip-audit -e src/data
```

For non-standard package layouts, identify one or more import roots explicitly:

```bash
yyds-pip-audit --source-root backend/src --source-root packages/shared
```

### 5. pyproject.toml Configuration

You can write configuration options directly in your project's `pyproject.toml` file under the `[tool.yyds-pip-audit]` section:

```toml
[tool.yyds-pip-audit]
exclude = ["build_assets", "custom_dir"]
source_roots = ["src"]
format = "json"
output = "audit_report.json"
fail_on = "missing"
evaluate_markers = true
```

Command-line parameters always override values from the configuration file.
Configuration-controlled output paths are resolved relative to the project and cannot escape it.

## 📋 Command Line Interface

```
Usage: yyds-pip-audit [OPTIONS] [DIRECTORY]

  yyds-pip-audit: A robust Python package import dependency auditor and PyPI mapper.

Options:
  -o, --output PATH               Save dependencies output to target file (e.g. requirements.txt)
  -f, --format [text|requirements|json]
                                  Output format: text (colored table), requirements (standard), json (JSON data) [default: text]
  -e, --exclude TEXT              Extra directory names to exclude (can be specified multiple times)
  --source-root TEXT              Project import root used to identify local packages
  -c, --check PATH                Compare against an existing requirements file to detect missing or unused packages
  --fail-on [none|missing|unused|any]
                                  Return exit code 1 for selected comparison findings
  --include-unresolved / --skip-unresolved
                                  Include or skip unverified package guesses
  --evaluate-markers / --ignore-markers
                                  Select whether environment markers are evaluated
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
2. **Hardcoded Fallbacks**: Includes mappings for common packages that might not be installed or don't declare `top_level.txt`.

Each result includes a `resolution` value (`metadata`, `fallback`, or `unresolved`).
Unresolved names are not exported as installable requirements by default; pass
`--include-unresolved` only after reviewing them.

## Development

```bash
pip install -e ".[test,build,lint]"
pytest --cov --cov-report=term-missing
ruff check yyds_pip_audit tests
./build.sh                 # build and validate, without uploading
./build.sh --upload        # explicit PyPI upload
```

## 📄 License

This project is licensed under the [MIT](https://github.com/yyds-fast/yyds-pip-audit/blob/main/LICENSE) License.
