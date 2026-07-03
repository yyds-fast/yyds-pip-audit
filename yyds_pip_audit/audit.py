# -*- coding:utf-8 -*-

import ast
import os
import sys
import re
from pathlib import Path
import importlib.metadata

# Default directories to ignore during traversal
DEFAULT_EXCLUDES = {
    '.venv', 'venv', 'env', '.env', '__pycache__', '.git', '.idea',
    'build', 'dist', 'node_modules', '.pytest_cache', '.tox',
    '.mypy_cache', '.hg', '.svn', 'egg-info'
}

# Standard library fallback list for Python versions < 3.10
STD_LIBS = {
    "abc", "argparse", "ast", "asynchat", "asyncio", "asyncore", "base64", "bdb", "binascii",
    "bisect", "builtins", "bz2", "calendar", "cgi", "cgitb", "chunk", "cmath", "cmd", "code",
    "codecs", "codeop", "collections", "colorsys", "compileall", "concurrent", "configparser",
    "contextlib", "contextvars", "copy", "copyreg", "crypt", "csv", "ctypes", "curses",
    "dataclasses", "datetime", "dbm", "decimal", "difflib", "dis", "distutils", "doctest",
    "email", "encodings", "ensurepip", "enum", "errno", "faulthandler", "filecmp", "fileinput",
    "fnmatch", "fractions", "ftplib", "functools", "gc", "getopt", "getpass", "gettext",
    "glob", "graphlib", "grp", "gzip", "hashlib", "heapq", "hmac", "html", "http", "imaplib",
    "imghdr", "imp", "importlib", "inspect", "io", "ipaddress", "itertools", "json", "keyword",
    "lib2to3", "linecache", "locale", "logging", "lzma", "mailbox", "mailcap", "marshal",
    "math", "mimetypes", "mmap", "modulefinder", "msilib", "multiprocessing", "netrc", "nis",
    "nntplib", "numbers", "operator", "optparse", "os", "ossaudiodev", "pathlib", "pdb",
    "pickle", "pickletools", "pipes", "pkgutil", "platform", "plistlib", "poplib", "posix",
    "posixpath", "pprint", "profile", "pstats", "pty", "pwd", "py_compile", "pyclbr", "pydoc",
    "queue", "quopri", "random", "re", "readline", "reprlib", "resource", "rlcompleter",
    "runpy", "sched", "select", "selectors", "shelve", "shlex", "shutil", "signal", "site",
    "smtpd", "smtplib", "sndhdr", "socket", "socketserver", "spwd", "sqlite3", "ssl", "stat",
    "statistics", "string", "stringprep", "struct", "subprocess", "sunau", "symtable", "sys",
    "sysconfig", "syslog", "tabnanny", "tarfile", "telnetlib", "tempfile", "termios", "test",
    "textwrap", "threading", "time", "timeit", "tkinter", "token", "tokenize", "tomllib",
    "trace", "traceback", "tracemalloc", "tty", "types", "typing", "unicodedata", "unittest",
    "urllib", "uu", "uuid", "warnings", "wave", "weakref", "webbrowser", "winreg", "winsound",
    "wsgiref", "xdg", "xml", "xmlrpc", "zipapp", "zipfile", "zipimport", "zlib", "zoneinfo"
}

def should_exclude(dir_name, exclude_dirs=None):
    """
    Check if a directory should be excluded from scanning
    """
    if exclude_dirs is None:
        exclude_dirs = DEFAULT_EXCLUDES
    
    # Direct match or contains match
    if dir_name in exclude_dirs:
        return True
    
    # Substring / pattern matching
    if dir_name.endswith('.egg-info'):
        return True
        
    return False

def build_local_import_mapping():
    """
    Stream-scans metadata of all installed distributions in the environment
    and builds a reverse mapping: [imported module name -> PyPI package name]
    """
    mapping = {}
    
    # Traverse all installed distributions in the active python environment
    for dist in importlib.metadata.distributions():
        try:
            # Metadata keys can be normalized
            package_name = dist.metadata.get('Name') or dist.name
            if not package_name:
                continue
        except Exception:
            continue

        # Try reading top_level.txt; handle exceptions by falling back
        top_levels = None
        try:
            top_levels = dist.read_text('top_level.txt')
        except Exception:
            pass

        if top_levels:
            try:
                for line in top_levels.splitlines():
                    line = line.strip()
                    if line and not line.startswith('#'):
                        # Map importable name to package name (e.g. "cv2" -> "opencv-python")
                        mapping[line] = package_name
            except Exception:
                pass
        else:
            # If top_level.txt is missing, normalize name to create import mapping
            norm_name = package_name.lower().replace('-', '_')
            mapping[norm_name] = package_name
            mapping[package_name] = package_name

    # Common PyPI packages with non-standard import/package names
    hardcoded_fallback = {
        "cv2": "opencv-python",
        "PIL": "Pillow",
        "onnxruntime": "onnxruntime" if "onnxruntime" in mapping else "onnxruntime-gpu",
        "yaml": "PyYAML",
        "git": "GitPython",
        "docker": "docker",
        "jwt": "PyJWT",
        "bs4": "beautifulsoup4",
        "github": "PyGithub",
        "dateutil": "python-dateutil",
        "jose": "python-jose",
        "kubernetes": "kubernetes",
        "slack": "slack-sdk",
        "google": "google-api-python-client",
        "mpl_toolkits": "matplotlib",
        "matplotlib": "matplotlib",
        "fitz": "PyMuPDF",
        "jinja2": "Jinja2",
        "zmq": "pyzmq",
        "docx": "python-docx",
        "pptx": "python-pptx",
        "openpyxl": "openpyxl",
    }
    
    for k, v in hardcoded_fallback.items():
        if k not in mapping:
            mapping[k] = v
            
    return mapping

def extract_imports(project_dir, exclude_dirs=None):
    """
    扫描 project_dir，解析本地模块、标准库模块，并提取第三方导入模块名称。
    合并了双次 Walk，进行了快速字符串过滤优化。
    """
    if exclude_dirs is None:
        exclude_dirs = DEFAULT_EXCLUDES
    else:
        exclude_dirs = set(exclude_dirs).union(DEFAULT_EXCLUDES)

    imported_modules = set()
    local_files = set()
    project_path = Path(project_dir).resolve()

    # 一次 os.walk 完成本地模块注册和第三方导入提取
    for root, dirs, files in os.walk(project_path):
        # 排除指定的忽略目录
        dirs[:] = [d for d in dirs if not should_exclude(d, exclude_dirs)]
        
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                rel_path = Path(file_path)
                
                # 1. 注册本地文件/模块
                local_files.add(rel_path.stem)
                try:
                    # 排除最顶层的包名/目录名
                    local_files.add(rel_path.relative_to(project_path).parts[0])
                except Exception:
                    pass
                
                # 2. 提取导入
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    
                    # 快速初筛：如果文件里完全不包含 "import" 关键字，则无需进行 AST 解析
                    if 'import' not in content:
                        continue
                        
                    tree = ast.parse(content, filename=file_path)
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                imported_modules.add(alias.name.split('.')[0])
                        elif isinstance(node, ast.ImportFrom) and node.level == 0:
                            if node.module:
                                imported_modules.add(node.module.split('.')[0])
                except Exception:
                    continue

    # 3. 扣除标准库、本地模块、自身库名等
    stdlib = getattr(sys, 'stdlib_module_names', set())
    if not stdlib:
        stdlib = STD_LIBS
    else:
        stdlib = stdlib.union(STD_LIBS)
        
    third_party = imported_modules - stdlib - local_files - {'', 'yyds_pip_audit', 'yyds-pip-audit'}
    return sorted(list(third_party))

def audit_dependencies(project_dir, exclude_dirs=None):
    """
    Audits imports in the project_dir and maps them to PyPI package names and versions.
    """
    imported_mods = extract_imports(project_dir, exclude_dirs)
    import_to_pypi = build_local_import_mapping()
    
    results = []
    for mod in imported_mods:
        # Determine PyPI package name from mapping or fallback to import name
        pypi_name = import_to_pypi.get(mod, mod)
        
        installed_version = None
        status = "not_installed"
        
        try:
            # Check locally installed version
            installed_version = importlib.metadata.version(pypi_name)
            status = "installed"
        except importlib.metadata.PackageNotFoundError:
            # If not found under matched name, retry under normalized module name
            try:
                installed_version = importlib.metadata.version(mod)
                status = "installed"
                pypi_name = mod
            except importlib.metadata.PackageNotFoundError:
                pass
                
        results.append({
            "import_name": mod,
            "pypi_name": pypi_name,
            "version": installed_version,
            "status": status
        })
        
    return results

def parse_requirements_file(file_path):
    """
    Parses a requirements.txt file and returns a dictionary of package names mapped to lines.
    """
    packages = {}
    if not os.path.exists(file_path):
        return packages
        
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            # Extract package name by stripping version specifiers
            parts = re.split(r'==|>=|<=|>|<|~=|!=|;', line)
            if parts:
                pkg_name = parts[0].strip()
                # Normalize name for robust lookup (case-insensitive, dash/underscore normalized)
                norm_name = pkg_name.lower().replace('_', '-')
                packages[norm_name] = {
                    "raw": line,
                    "name": pkg_name
                }
    return packages
