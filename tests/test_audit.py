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
    assert should_exclude('some_package.egg-info') is True
    assert should_exclude('my_custom_dir', exclude_dirs={'my_custom_dir'}) is True

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

