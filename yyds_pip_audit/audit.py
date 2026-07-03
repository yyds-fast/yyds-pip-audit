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
    '.mypy_cache', '.hg', '.svn', 'egg-info',
    # Common non-code/asset directories
    'data', 'dataset', 'datasets', 'static', 'media', 'assets',
    'public', 'uploads', 'logs', 'log', 'tmp', 'temp', 'htmlcov'
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

# Regex to pre-filter files containing actual python imports
IMPORT_RE = re.compile(r'(?:^|;)\s*(?:import\s+|from\s+[\w\.]+\s+import\s+)', re.MULTILINE)

class ImportVisitor(ast.NodeVisitor):
    """
    Optimized AST visitor that extracts absolute imports,
    bypassing expression-level leaf nodes to accelerate traversal.
    """
    def __init__(self):
        self.imports = set()

    def visit_Import(self, node):
        for alias in node.names:
            self.imports.add(alias.name)

    def visit_ImportFrom(self, node):
        if node.level == 0 and node.module:
            for alias in node.names:
                # Store full import path for namespace matching (e.g. google.cloud.storage)
                self.imports.add(f"{node.module}.{alias.name}")

    # No-ops to skip deep traversal of expressions and simple statements
    def visit_Expr(self, node): pass
    def visit_Assign(self, node): pass
    def visit_AugAssign(self, node): pass
    def visit_AnnAssign(self, node): pass
    def visit_Return(self, node): pass
    def visit_Delete(self, node): pass
    def visit_Assert(self, node): pass
    def visit_Global(self, node): pass
    def visit_Nonlocal(self, node): pass
    def visit_Pass(self, node): pass
    def visit_Break(self, node): pass
    def visit_Continue(self, node): pass
    def visit_Name(self, node): pass
    def visit_Constant(self, node): pass

def should_exclude(dir_name, rel_path_str="", exclude_dirs=None):
    """
    Check if a directory should be excluded from scanning.
    Supports matching the base directory name (e.g., 'venv') or its relative path (e.g., 'src/data').
    """
    if exclude_dirs is None:
        exclude_dirs = DEFAULT_EXCLUDES
    
    # Normalize relative path separators to forward slashes for cross-platform consistency
    norm_rel_path = rel_path_str.replace('\\', '/')
    
    # Check both the directory name and relative path against exclusions
    if dir_name in exclude_dirs or norm_rel_path in exclude_dirs:
        return True
    
    # Substring / pattern matching
    if dir_name.endswith('.egg-info'):
        return True
        
    return False

def build_local_import_mapping(imported_top_levels=None):
    """
    Stream-scans metadata of all installed distributions in the environment
    and builds a reverse mapping: [imported module name -> PyPI package name].
    Supports namespace packages using dist.files matching.
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

        # Get top-level names for this package to check if it's imported
        top_levels = []
        try:
            top_txt = dist.read_text('top_level.txt')
            if top_txt:
                top_levels = [line.strip() for line in top_txt.splitlines() if line.strip() and not line.startswith('#')]
        except Exception:
            pass

        if not top_levels:
            top_levels = [package_name.lower().replace('-', '_'), package_name]

        # Optimization: skip packages that are not imported by the project at all
        if imported_top_levels is not None:
            if not any(tl in imported_top_levels for tl in top_levels):
                continue

        # Try mapping files first (best support for namespaces)
        has_files_mapping = False
        try:
            if dist.files:
                for file_path in dist.files:
                    path_str = str(file_path).replace('\\', '/')
                    if path_str.endswith('.py'):
                        parts = list(Path(path_str).parts)
                        # Exclude build files, virtualenv leftovers, metadata directories
                        if any(p.startswith('.') or p.endswith('.dist-info') or p.endswith('.egg-info') for p in parts):
                            continue
                        
                        if parts[-1] == '__init__.py':
                            parts.pop()
                        else:
                            parts[-1] = Path(parts[-1]).stem
                            
                        if parts and all(p.isidentifier() for p in parts):
                            mod_path = ".".join(parts)
                            mapping[mod_path] = package_name
                            has_files_mapping = True
        except Exception:
            pass

        if not has_files_mapping:
            for tl in top_levels:
                mapping[tl] = package_name

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
    合并了双次 Walk，进行了快速正则初筛与 AST 剪枝优化。
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
        # 排除指定的忽略目录，包含相对路径的精准匹配
        pruned_dirs = []
        for d in dirs:
            dir_full_path = Path(root) / d
            try:
                rel_path = dir_full_path.relative_to(project_path)
                rel_path_str = str(rel_path)
            except Exception:
                rel_path_str = d
                
            if should_exclude(d, rel_path_str, exclude_dirs):
                continue
            pruned_dirs.append(d)
            
        # 原地修改 dirs 以进行剪枝，不再向下遍历被忽略的目录
        dirs[:] = pruned_dirs
        
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
                    # 过滤超过 2MB 的超大生成文件，防止 AST 树解析过慢
                    if os.path.getsize(file_path) > 2 * 1024 * 1024:
                        continue
                        
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    
                    # 快速正则初筛：如果文件里不包含实际导入动作，则无需进行 AST 解析
                    if not IMPORT_RE.search(content):
                        continue
                        
                    tree = ast.parse(content, filename=file_path)
                    visitor = ImportVisitor()
                    visitor.visit(tree)
                    imported_modules.update(visitor.imports)
                except Exception:
                    continue

    # 3. 扣除标准库、本地模块、自身库名等
    stdlib = getattr(sys, 'stdlib_module_names', set())
    if not stdlib:
        stdlib = STD_LIBS
    else:
        stdlib = stdlib.union(STD_LIBS)
        
    filtered_imports = set()
    for imp in imported_modules:
        first_comp = imp.split('.')[0]
        if first_comp not in stdlib and first_comp not in local_files and first_comp not in {'', 'yyds_pip_audit', 'yyds-pip-audit'}:
            filtered_imports.add(imp)
            
    return sorted(list(filtered_imports))

def resolve_pypi_name(import_path, import_to_pypi):
    """
    通过最长前缀匹配，将导入路径解析为 PyPI 包名。
    返回 (pypi_name, matched_prefix)
    """
    parts = import_path.split('.')
    while parts:
        candidate = ".".join(parts)
        if candidate in import_to_pypi:
            return import_to_pypi[candidate], candidate
        parts.pop()
    # 兜底截取首个模块名
    first_comp = import_path.split('.')[0]
    return first_comp, first_comp

def audit_dependencies(project_dir, exclude_dirs=None):
    """
    Audits imports in the project_dir and maps them to PyPI package names and versions.
    Groups results by PyPI package name to handle namespace packages and duplicate submodules.
    """
    imported_mods = extract_imports(project_dir, exclude_dirs)
    imported_top_levels = {mod.split('.')[0] for mod in imported_mods}
    import_to_pypi = build_local_import_mapping(imported_top_levels)
    
    grouped_results = {}
    for mod in imported_mods:
        pypi_name, import_name = resolve_pypi_name(mod, import_to_pypi)
        
        if pypi_name in grouped_results:
            grouped_results[pypi_name]["import_names"].add(import_name)
            continue
            
        installed_version = None
        status = "not_installed"
        
        try:
            # Check locally installed version
            installed_version = importlib.metadata.version(pypi_name)
            status = "installed"
        except importlib.metadata.PackageNotFoundError:
            # If not found under matched name, retry under normalized module name
            try:
                installed_version = importlib.metadata.version(import_name)
                status = "installed"
                pypi_name = import_name
            except importlib.metadata.PackageNotFoundError:
                pass
                
        grouped_results[pypi_name] = {
            "import_names": {import_name},
            "pypi_name": pypi_name,
            "version": installed_version,
            "status": status
        }
        
    results = []
    for pypi_name, info in grouped_results.items():
        results.append({
            "import_name": ", ".join(sorted(list(info["import_names"]))),
            "pypi_name": info["pypi_name"],
            "version": info["version"],
            "status": info["status"]
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
