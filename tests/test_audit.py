# -*- coding:utf-8 -*-

import os
import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from yyds_pip_audit.audit import (
    extract_imports,
    should_exclude,
    build_local_import_mapping,
    audit_dependencies,
    parse_requirements_file
)

def test_should_exclude():
    assert should_exclude('.venv') is True
    assert should_exclude('venv') is True
    assert should_exclude('src') is False
    assert should_exclude('data') is True  # Default excludes
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
    from yyds_pip_audit.audit import should_exclude_dir
    from pathlib import Path
    
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


def test_format_display_imports():
    from yyds_pip_audit.cli import format_display_imports
    
    assert format_display_imports("") == ""
    assert format_display_imports("requests") == "requests"
    assert format_display_imports("requests, pillow") == "requests, pillow"
    assert format_display_imports("a, b, c") == "a, b, c"
    assert format_display_imports("a, b, c, d") == "a, b, c ... (+1 more)"
    assert format_display_imports("a, b, c, d, e, f") == "a, b, c ... (+3 more)"

