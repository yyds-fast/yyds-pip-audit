# -*- coding:utf-8 -*-

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from yyds_pip_audit.audit import (
    audit_dependencies,
    build_local_import_mapping,
    extract_imports,
    parse_requirements_file,
    should_exclude,
)


def test_should_exclude():
    assert should_exclude('.venv') is True
    assert should_exclude('venv') is True
    assert should_exclude('src') is False
    assert should_exclude('data') is False  # Application directories are scanned
    assert should_exclude('some_package.egg-info') is True
    assert should_exclude('my_custom_dir', exclude_dirs={'my_custom_dir'}) is True
    
    # Test relative path matching
    assert should_exclude('data', 'src/data', exclude_dirs={'src/data'}) is True
    assert should_exclude('other', 'src/other', exclude_dirs={'src/data'}) is False

def test_parse_requirements_file(tmp_path):
    req_file = tmp_path / "requirements.txt"
    req_file.write_text(
        "opencv-python==4.8.0.76\n"
        "PyYAML>=6.0\n"
        "# this is a comment\n"
        "   \n"
        "unused-package==1.0.0\n",
        encoding="utf-8"
    )
    
    parsed = parse_requirements_file(str(req_file))
    assert "opencv-python" in parsed
    assert "pyyaml" in parsed
    assert "unused-package" in parsed
    assert parsed["opencv-python"]["name"] == "opencv-python"
    assert parsed["pyyaml"]["raw"] == "PyYAML>=6.0"

def test_extract_imports_and_local_modules(tmp_path):
    # Create a mock project structure
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()
    
    # Create main.py
    main_file = project_dir / "main.py"
    main_file.write_text(
        "import os\n"
        "import sys\n"
        "import requests\n"
        "from PIL import Image\n"
        "import local_module\n"
        "from subpkg import helper\n",
        encoding="utf-8"
    )
    
    # Create local_module.py
    local_module = project_dir / "local_module.py"
    local_module.write_text("def run(): pass\n", encoding="utf-8")
    
    # Create subpkg/helper.py
    subpkg = project_dir / "subpkg"
    subpkg.mkdir()
    subpkg_init = subpkg / "__init__.py"
    subpkg_init.write_text("", encoding="utf-8")
    subpkg_helper = subpkg / "helper.py"
    subpkg_helper.write_text("def help(): pass\n", encoding="utf-8")
    
    # Scan
    imports = extract_imports(str(project_dir))
    
    # Expected results:
    # - 'os', 'sys' are standard libraries, so they should be filtered out.
    # - 'local_module', 'subpkg' are local modules/packages, so they should be filtered out.
    # - 'requests' and 'PIL' are third-party, so they should be present.
    
    assert "requests" in imports
    assert "PIL.Image" in imports
    assert "os" not in imports
    assert "sys" not in imports
    assert "local_module" not in imports
    assert "subpkg" not in imports


def test_extract_imports_detects_dynamic_only_files(tmp_path):
    project_dir = tmp_path / "dynamic_project"
    project_dir.mkdir()
    (project_dir / "plugins.py").write_text(
        "__import__('numpy')\n"
        "importlib.import_module('pandas')\n",
        encoding="utf-8",
    )

    imports = extract_imports(str(project_dir))

    assert "numpy" in imports
    assert "pandas" in imports


def test_extract_imports_supports_src_layout(tmp_path):
    project_dir = tmp_path / "src_project"
    package_dir = project_dir / "src" / "my_package"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (project_dir / "main.py").write_text(
        "import my_package\nimport requests\n",
        encoding="utf-8",
    )

    imports = extract_imports(str(project_dir))

    assert "my_package" not in imports
    assert "requests" in imports


def test_nested_module_does_not_hide_external_import(tmp_path):
    project_dir = tmp_path / "shadow_project"
    tests_dir = project_dir / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "requests.py").write_text("", encoding="utf-8")
    (project_dir / "main.py").write_text("import requests\n", encoding="utf-8")

    assert "requests" in extract_imports(str(project_dir))


def test_gitignore_patterns_are_applied(tmp_path):
    project_dir = tmp_path / "ignored_project"
    generated_dir = project_dir / "generated"
    ignored_dir = project_dir / "ignored_dir"
    nested_dir = project_dir / "nested"
    generated_dir.mkdir(parents=True)
    ignored_dir.mkdir()
    nested_dir.mkdir()
    (project_dir / ".gitignore").write_text(
        "generated/*.py\n"
        "!generated/keep.py\n"
        "/root_only.py\n"
        "ignored_dir/\n",
        encoding="utf-8",
    )
    (generated_dir / "ignored.py").write_text("import numpy\n", encoding="utf-8")
    (generated_dir / "keep.py").write_text("import pandas\n", encoding="utf-8")
    (project_dir / "root_only.py").write_text("import flask\n", encoding="utf-8")
    (nested_dir / "root_only.py").write_text("import requests\n", encoding="utf-8")
    (ignored_dir / "module.py").write_text("import django\n", encoding="utf-8")

    imports = extract_imports(str(project_dir))

    assert "pandas" in imports
    assert "requests" in imports
    assert "numpy" not in imports
    assert "flask" not in imports
    assert "django" not in imports


def test_xdg_is_not_treated_as_standard_library(tmp_path):
    (tmp_path / "main.py").write_text("import xdg\n", encoding="utf-8")

    assert "xdg" in extract_imports(str(tmp_path))


def test_python_symlink_outside_project_is_skipped(tmp_path):
    project_dir = tmp_path / "symlink_project"
    project_dir.mkdir()
    outside_file = tmp_path / "outside.py"
    outside_file.write_text("import should_not_leak\n", encoding="utf-8")
    try:
        (project_dir / "linked.py").symlink_to(outside_file)
    except OSError:
        pytest.skip("Symbolic links are not available on this platform")

    assert "should_not_leak" not in extract_imports(str(project_dir))


def test_audit_marks_unknown_mapping_as_unresolved(tmp_path):
    package_name = "definitely_yyds_internal_package"
    (tmp_path / "main.py").write_text(f"import {package_name}\n", encoding="utf-8")

    result = audit_dependencies(str(tmp_path))

    assert result == [
        {
            "import_name": package_name,
            "pypi_name": package_name,
            "version": None,
            "status": "not_installed",
            "resolution": "unresolved",
        }
    ]

@patch('importlib.metadata.distributions')
def test_build_local_import_mapping(mock_dists):
    # Mock some distributions
    mock_dist1 = MagicMock()
    mock_dist1.metadata = {'Name': 'opencv-python'}
    mock_dist1.read_text.return_value = "cv2"
    
    mock_dist2 = MagicMock()
    mock_dist2.metadata = {'Name': 'Pillow'}
    mock_dist2.read_text.return_value = "PIL\n# comment"
    
    mock_dist3 = MagicMock()
    mock_dist3.metadata = {'Name': 'requests'}
    # read_text raises exception to test fallback
    mock_dist3.read_text.side_effect = Exception("No top_level.txt")
    
    mock_dists.return_value = [mock_dist1, mock_dist2, mock_dist3]
    
    mapping = build_local_import_mapping()
    
    assert mapping["cv2"] == "opencv-python"
    assert mapping["PIL"] == "Pillow"
    # Fallback normalizations
    assert mapping["requests"] == "requests"
    # Hardcoded fallbacks
    assert mapping["yaml"] == "PyYAML"


@patch('importlib.metadata.distributions')
def test_build_mapping_uses_files_for_nonstandard_name(mock_dists):
    dist = MagicMock()
    dist.metadata = {'Name': 'different-distribution-name'}
    dist.read_text.return_value = None
    dist.files = [Path('unusual_import/__init__.py')]
    mock_dists.return_value = [dist]

    mapping = build_local_import_mapping({'unusual_import'})

    assert mapping['unusual_import'] == 'different-distribution-name'
    assert mapping['onnxruntime'] == 'onnxruntime'

def test_resolve_pypi_name():
    from yyds_pip_audit.audit import resolve_pypi_name
    mapping = {
        "google.cloud.storage": "google-cloud-storage",
        "google.cloud.pubsub": "google-cloud-pubsub",
        "requests": "requests"
    }
    
    assert resolve_pypi_name("google.cloud.storage.blob", mapping) == ("google-cloud-storage", "google.cloud.storage")
    assert resolve_pypi_name("google.cloud.pubsub.client", mapping) == ("google-cloud-pubsub", "google.cloud.pubsub")
    assert resolve_pypi_name("requests.adapters", mapping) == ("requests", "requests")
    assert resolve_pypi_name("unknown_package", mapping) == ("unknown_package", "unknown_package")


def test_normalize_package_name():
    from yyds_pip_audit.audit import normalize_package_name
    assert normalize_package_name("google.cloud.storage") == "google-cloud-storage"
    assert normalize_package_name("Django") == "django"
    assert normalize_package_name("ruamel.yaml") == "ruamel-yaml"
    assert normalize_package_name("ruamel_yaml") == "ruamel-yaml"
    assert normalize_package_name("ruamel---yaml") == "ruamel-yaml"


def test_parse_requirements_file_advanced(tmp_path):
    from yyds_pip_audit.audit import parse_requirements_file
    
    # Create recursive requirements files
    req_sub = tmp_path / "requirements_sub.txt"
    req_sub.write_text("requests==2.26.0\npillow>=9.0.0\n", encoding="utf-8")
    
    req_main = tmp_path / "requirements.txt"
    req_main.write_text(
        f"-r {req_sub.name}\n"
        "Django==4.0\n"
        "-e git+https://github.com/psf/requests.git@v2.26.0#egg=requests\n"
        "google-cloud-storage @ https://github.com/.../google-cloud-storage-1.0.0.tar.gz\n"
        "numpy; python_version < '3.9'\n",
        encoding="utf-8"
    )
    
    parsed = parse_requirements_file(str(req_main))
    
    # Check that Django, requests, pillow, google-cloud-storage, numpy are all parsed
    assert "django" in parsed
    assert "requests" in parsed
    assert "pillow" in parsed
    assert "google-cloud-storage" in parsed
    assert "numpy" in parsed
    
    assert parsed["django"]["name"] == "Django"
    assert parsed["requests"]["name"] == "requests"
    assert parsed["pillow"]["name"] == "pillow"
    assert parsed["google-cloud-storage"]["name"] == "google-cloud-storage"
    assert parsed["numpy"]["name"] == "numpy"


def test_parse_requirements_handles_hashes_comments_and_markers(tmp_path):
    requirements = tmp_path / "requirements.txt"
    included = tmp_path / "included.txt"
    included.write_text("urllib3==2.2.0  # inline comment\n", encoding="utf-8")
    requirements.write_text(
        "-rincluded.txt  # compact include\n"
        "requests[security]==2.31.0 \\\n"
        "    --hash=sha256:abc123\n"
        "never-active; python_version < '0'\n"
        "always-active; python_version >= '3'\n",
        encoding="utf-8",
    )

    all_markers = parse_requirements_file(str(requirements))
    active_markers = parse_requirements_file(
        str(requirements),
        evaluate_markers=True,
    )

    assert {"urllib3", "requests", "never-active", "always-active"} <= set(all_markers)
    assert "never-active" not in active_markers
    assert "always-active" in active_markers


def test_parse_gitignore(tmp_path):
    from yyds_pip_audit.audit import parse_gitignore
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(
        "# Comments\n"
        "venv/\n"
        "custom/path/\n"
        "*.pyc\n",
        encoding="utf-8"
    )
    
    patterns = parse_gitignore(str(tmp_path))
    assert "venv" in patterns
    assert "custom/path" in patterns
    assert "*.pyc" in patterns


def test_should_exclude_dir():
    from pathlib import Path

    from yyds_pip_audit.audit import should_exclude_dir
    
    project_path = Path("/home/user/project")
    exclude_base = {"venv", "data"}
    exclude_paths = {Path("/home/user/project/src/custom")}
    
    assert should_exclude_dir("/home/user/project/venv", "venv", project_path, exclude_base, exclude_paths) is True
    assert should_exclude_dir("/home/user/project/src/custom", "custom", project_path, exclude_base, exclude_paths) is True
    assert should_exclude_dir("/home/user/project/src/custom/sub", "sub", project_path, exclude_base, exclude_paths) is True
    assert should_exclude_dir("/home/user/project/src/other", "other", project_path, exclude_base, exclude_paths) is False


def test_load_config_from_toml(tmp_path):
    from yyds_pip_audit.cli import load_config_from_toml
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "[tool.yyds-pip-audit]\n"
        "exclude = [\"build_assets\", \"custom_dir\"]\n"
        "format = \"json\"\n"
        "output = \"audit_report.json\"\n",
        encoding="utf-8"
    )
    
    config = load_config_from_toml(str(tmp_path))
    assert config.get("exclude") == ["build_assets", "custom_dir"]
    assert config.get("format") == "json"
    assert config.get("output") == "audit_report.json"


def test_import_visitor_dynamic():
    import ast

    from yyds_pip_audit.audit import ImportVisitor
    
    code = """
import requests
def load():
    importlib.import_module('pandas')
    __import__('numpy')
    importlib.import_module(dynamic_var) # should be skipped gracefully
"""
    tree = ast.parse(code)
    visitor = ImportVisitor()
    visitor.visit(tree)
    
    assert "requests" in visitor.imports
    assert "pandas" in visitor.imports
    assert "numpy" in visitor.imports


def test_import_visitor_dynamic_aliases():
    import ast

    from yyds_pip_audit.audit import ImportVisitor

    tree = ast.parse(
        "import importlib as il\n"
        "from importlib import import_module as load\n"
        "il.import_module('pandas')\n"
        "load('numpy')\n"
    )
    visitor = ImportVisitor()
    visitor.visit(tree)

    assert "pandas" in visitor.imports
    assert "numpy" in visitor.imports


def test_cli_main(tmp_path):
    from click.testing import CliRunner

    from yyds_pip_audit.cli import main
    
    # Create pyproject.toml and a python file
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "[tool.yyds-pip-audit]\n"
        "exclude = [\"custom_dir\"]\n",
        encoding="utf-8"
    )
    
    custom_dir = tmp_path / "custom_dir"
    custom_dir.mkdir()
    skipped_file = custom_dir / "skipped.py"
    skipped_file.write_text("import numpy\n", encoding="utf-8")
    
    main_file = tmp_path / "main.py"
    main_file.write_text("import requests\n", encoding="utf-8")
    
    runner = CliRunner()
    result = runner.invoke(main, [str(tmp_path), "-f", "json"])
    assert result.exit_code == 0
    
    import json
    data = json.loads(result.output)
    deps = [d["pypi_name"] for d in data["dependencies"]]
    assert "requests" in deps
    assert "numpy" not in deps


def test_cli_fail_on_missing(tmp_path):
    from click.testing import CliRunner

    from yyds_pip_audit.cli import main

    (tmp_path / "main.py").write_text("import requests\n", encoding="utf-8")
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("", encoding="utf-8")

    result = CliRunner().invoke(
        main,
        [str(tmp_path), "--check", str(requirements), "--fail-on", "missing", "-f", "json"],
    )

    assert result.exit_code == 1
    data = __import__('json').loads(result.output)
    assert data["check"]["missing"] == ["requests"]


def test_config_output_cannot_escape_project(tmp_path):
    from click.testing import CliRunner

    from yyds_pip_audit.cli import main

    project_dir = tmp_path / "unsafe_project"
    project_dir.mkdir()
    (project_dir / "main.py").write_text("import requests\n", encoding="utf-8")
    (project_dir / "pyproject.toml").write_text(
        "[tool.yyds-pip-audit]\n"
        "format = \"json\"\n"
        "output = \"../escaped.json\"\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(main, [str(project_dir)])

    assert result.exit_code != 0
    assert "must stay inside" in result.output
    assert not (tmp_path / "escaped.json").exists()


def test_requirements_export_skips_unresolved_by_default():
    from yyds_pip_audit.cli import requirements_lines

    results = [
        {
            "pypi_name": "requests",
            "version": "2.31.0",
            "status": "installed",
            "resolution": "metadata",
        },
        {
            "pypi_name": "company_internal",
            "version": None,
            "status": "not_installed",
            "resolution": "unresolved",
        },
    ]

    safe_lines, skipped = requirements_lines(results)
    all_lines, _ = requirements_lines(results, include_unresolved=True)

    assert safe_lines == ["requests==2.31.0"]
    assert skipped == ["company_internal"]
    assert "company_internal" in all_lines


def test_format_display_imports():
    from yyds_pip_audit.cli import format_display_imports
    
    assert format_display_imports("") == ""
    assert format_display_imports("requests") == "requests"
    assert format_display_imports("requests, pillow") == "requests, pillow"
    assert format_display_imports("a, b, c") == "a, b, c"
    assert format_display_imports("a, b, c, d") == "a, b, c ... (+1 more)"
    assert format_display_imports("a, b, c, d, e, f") == "a, b, c ... (+3 more)"
