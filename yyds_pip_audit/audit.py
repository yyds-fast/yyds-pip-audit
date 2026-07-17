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

def normalize_package_name(name):
    """
    Normalize package name according to PEP 503.
    Lowers the name and replaces any sequence of ., _, - with a single -.
    """
    if not name:
        return ""
    return re.sub(r'[-_.]+', '-', name).lower()

# Regex to pre-filter files containing actual python imports
IMPORT_RE = re.compile(r'\bimport\b')

class ImportVisitor(ast.NodeVisitor):
    """
    Optimized AST visitor that extracts absolute imports and static dynamic imports.
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

    def visit_Call(self, node):
        # Handle importlib.import_module('module_name')
        if isinstance(node.func, ast.Attribute):
            if (isinstance(node.func.value, ast.Name) and 
                node.func.value.id == 'importlib' and 
                node.func.attr == 'import_module'):
                if node.args:
                    val = None
                    if isinstance(node.args[0], ast.Constant):
                        val = node.args[0].value
                    elif hasattr(ast, 'Str') and isinstance(node.args[0], ast.Str):
                        val = node.args[0].s
                    if isinstance(val, str):
                        self.imports.add(val)
        # Handle __import__('module_name')
        elif isinstance(node.func, ast.Name) and node.func.id == '__import__':
            if node.args:
                val = None
                if isinstance(node.args[0], ast.Constant):
                    val = node.args[0].value
                elif hasattr(ast, 'Str') and isinstance(node.args[0], ast.Str):
                    val = node.args[0].s
                if isinstance(val, str):
                    self.imports.add(val)
        
        self.generic_visit(node)

def parse_gitignore(project_dir):
    """
    Parses .gitignore file in project_dir and returns a list of patterns to exclude.
    """
    patterns = []
    gitignore_path = os.path.join(project_dir, '.gitignore')
    if os.path.exists(gitignore_path):
        try:
            with open(gitignore_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    # Remove trailing slashes and normalize separators
                    if line.endswith('/'):
                        line = line[:-1]
                    line = line.replace('\\', '/')
                    patterns.append(line)
        except Exception:
            pass
    return patterns

def should_exclude(dir_name, rel_path_str="", exclude_dirs=None):
    """
    Check if a directory should be excluded from scanning (backward compatibility).
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

def should_exclude_dir(dir_full_path, dir_name, project_path, exclude_base_names, exclude_absolute_paths):
    """
    Determine if a directory should be excluded from search.
    """
    if dir_name in exclude_base_names:
        return True
    
    # Check if absolute path matches or starts with any of the excluded absolute paths
    try:
        dir_abs = Path(dir_full_path).resolve()
        for p in exclude_absolute_paths:
            if dir_abs == p or p in dir_abs.parents:
                return True
    except Exception:
        pass
        
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
        "PIL": "Pillow",
        "OpenSSL": "pyOpenSSL",
        "apiclient": "google-api-python-client",
        "apscheduler": "APScheduler",
        "argon2": "argon2-cffi",
        "arrow": "arrow",
        "async_timeout": "async-timeout",
        "attr": "attrs",
        "backoff": "backoff",
        "backports": "backports",
        "bcrypt": "bcrypt",
        "beautifulsoup4": "beautifulsoup4",
        "blessed": "blessed",
        "brotli": "Brotli",
        "bs4": "beautifulsoup4",
        "celery": "celery",
        "certifi": "certifi",
        "cffi": "cffi",
        "charset_normalizer": "charset-normalizer",
        "clearml": "clearml",
        "click": "click",
        "colorama": "colorama",
        "comet_ml": "comet-ml",
        "croniter": "croniter",
        "cryptography": "cryptography",
        "Crypto": "pycryptodome",
        "Cryptodome": "pycryptodomex",
        "cssselect": "cssselect",
        "cv2": "opencv-python",
        "dateutil": "python-dateutil",
        "decorator": "decorator",
        "discord": "discord.py",
        "distro": "distro",
        "docx": "python-docx",
        "docker": "docker",
        "dotenv": "python-dotenv",
        "elasticsearch": "elasticsearch",
        "eventlet": "eventlet",
        "fabric": "fabric",
        "fastapi": "fastapi",
        "fasttext": "fasttext",
        "fitz": "PyMuPDF",
        "flask": "Flask",
        "django": "Django",
        "gensim": "gensim",
        "gevent": "gevent",
        "git": "GitPython",
        "github": "PyGithub",
        "github3": "github3.py",
        "google": "google-api-python-client",
        "google.cloud.bigquery": "google-cloud-bigquery",
        "google.cloud.firestore": "google-cloud-firestore",
        "google.cloud.iam": "google-cloud-iam",
        "google.cloud.logging": "google-cloud-logging",
        "google.cloud.monitoring": "google-cloud-monitoring",
        "google.cloud.pubsub": "google-cloud-pubsub",
        "google.cloud.secretmanager": "google-cloud-secretmanager",
        "google.cloud.storage": "google-cloud-storage",
        "google.cloud.translate": "google-cloud-translate",
        "google.cloud.vision": "google-cloud-vision",
        "googleapiclient": "google-api-python-client",
        "gpustat": "gpustat",
        "greenlet": "greenlet",
        "gunicorn": "gunicorn",
        "huggingface_hub": "huggingface-hub",
        "humanize": "humanize",
        "idna": "idna",
        "importlib_metadata": "importlib-metadata",
        "importlib_resources": "importlib-resources",
        "inflect": "inflect",
        "inquirer": "inquirer",
        "invoke": "invoke",
        "jieba": "jieba",
        "jinja2": "Jinja2",
        "jose": "python-jose",
        "jwt": "PyJWT",
        "kombu": "kombu",
        "kubernetes": "kubernetes",
        "command": "click", # Fallback for CLI/command packages
        "langdetect": "langdetect",
        "langid": "langid",
        "lz4": "lz4",
        "lxml": "lxml",
        "matplotlib": "matplotlib",
        "mlflow": "mlflow",
        "mpl_toolkits": "matplotlib",
        "msgpack": "msgpack",
        "mysql": "mysql-connector-python",
        "nltk": "nltk",
        "onnxruntime": "onnxruntime" if "onnxruntime" in mapping else "onnxruntime-gpu",
        "openpyxl": "openpyxl",
        "opensearchpy": "opensearch-py",
        "packaging": "packaging",
        "paramiko": "paramiko",
        "passlib": "passlib",
        "pdfminer": "pdfminer.six",
        "peft": "peft",
        "pendulum": "pendulum",
        "pexpect": "pexpect",
        "pika": "pika",
        "platformdirs": "platformdirs",
        "playwright": "playwright",
        "pptx": "python-pptx",
        "prometheus_client": "prometheus-client",
        "prompt_toolkit": "prompt-toolkit",
        "psutil": "psutil",
        "ptyprocess": "ptyprocess",
        "pydantic": "pydantic",
        "pycparser": "pycparser",
        "pygments": "Pygments",
        "pymysql": "PyMySQL",
        "pynvml": "pynvml",
        "pypdf": "pypdf",
        "PyPDF2": "PyPDF2",
        "pypinyin": "pypinyin",
        "pyquery": "pyquery",
        "pytest": "pytest",
        "pytz": "pytz",
        "redis": "redis",
        "regex": "regex",
        "reportlab": "reportlab",
        "retrying": "retrying",
        "rich": "rich",
        "sacrebleu": "sacrebleu",
        "sacremoses": "sacremoses",
        "scapy": "scapy",
        "scrapy": "Scrapy",
        "sdk_updater": "android_sdk_updater",
        "selenium": "selenium",
        "sentence_transformers": "sentence-transformers",
        "sentencepiece": "sentencepiece",
        "sentry_sdk": "sentry-sdk",
        "serial": "pyserial",
        "setuptools_scm": "setuptools-scm",
        "skimage": "scikit-image",
        "sklearn": "scikit-learn",
        "slack": "slack-sdk",
        "slack_sdk": "slack-sdk",
        "snappy": "python-snappy",
        "snownlp": "snownlp",
        "socketio": "python-socketio",
        "spacy": "spacy",
        "sqlalchemy": "SQLAlchemy",
        "starlette": "starlette",
        "subword_nmt": "subword-nmt",
        "telegram": "python-telegram-bot",
        "tenacity": "tenacity",
        "tensorboardX": "tensorboardX",
        "tiktoken": "tiktoken",
        "tornado": "tornado",
        "tqdm": "tqdm",
        "twisted": "Twisted",
        "typer": "typer",
        "typing_extensions": "typing-extensions",
        "tzlocal": "tzlocal",
        "uvicorn": "uvicorn",
        "uvloop": "uvloop",
        "wandb": "wandb",
        "weasyprint": "WeasyPrint",
        "websocket": "websocket-client",
        "wrapt": "wrapt",
        "xlsxwriter": "XlsxWriter",
        "xxhash": "xxhash",
        "yaml": "PyYAML",
        "youtokentome": "youtokentome",
        "zhon": "zhon",
        "zipp": "zipp",
        "zmq": "pyzmq",
        "zstandard": "zstandard",
    }
    
    for k, v in hardcoded_fallback.items():
        if k not in mapping:
            mapping[k] = v
            
    return mapping

def extract_imports(project_dir, exclude_dirs=None):
    """
    扫描 project_dir，解析本地模块、标准库模块，并提取第三方导入模块名称。
    支持 .gitignore 自动集成与绝对/相对路径匹配。
    """
    project_path = Path(project_dir).resolve()
    
    # 1. 汇总所有排除模式
    raw_excludes = set(DEFAULT_EXCLUDES)
    if exclude_dirs:
        raw_excludes.update(exclude_dirs)
    
    # 自动加载 .gitignore 规则
    git_ignores = parse_gitignore(project_path)
    raw_excludes.update(git_ignores)

    # 2. 划分排除条件：基础名 vs 绝对路径
    exclude_base_names = set()
    exclude_absolute_paths = set()
    
    for item in raw_excludes:
        if '/' in item or '\\' in item or os.path.isabs(item):
            try:
                abs_path = (project_path / item).resolve()
                exclude_absolute_paths.add(abs_path)
            except Exception:
                pass
        else:
            exclude_base_names.add(item)

    imported_modules = set()
    local_files = set()

    # 3. os.walk 单次遍历
    for root, dirs, files in os.walk(project_path):
        pruned_dirs = []
        for d in dirs:
            dir_full_path = Path(root) / d
            if should_exclude_dir(dir_full_path, d, project_path, exclude_base_names, exclude_absolute_paths):
                continue
            pruned_dirs.append(d)
            
        # 原地剪枝
        dirs[:] = pruned_dirs
        
        for file in files:
            file_path = os.path.join(root, file)
            file_abs_path = Path(file_path).resolve()
            
            # 过滤排除的文件
            if file in exclude_base_names or file_abs_path in exclude_absolute_paths:
                continue
                
            if file.endswith('.py'):
                rel_path = Path(file_path)
                
                # 注册本地模块
                local_files.add(rel_path.stem)
                try:
                    local_files.add(rel_path.relative_to(project_path).parts[0])
                except Exception:
                    pass
                
                # 提取导入
                try:
                    if os.path.getsize(file_path) > 2 * 1024 * 1024:
                        continue
                        
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    
                    if not IMPORT_RE.search(content):
                        continue
                        
                    tree = ast.parse(content, filename=file_path)
                    visitor = ImportVisitor()
                    visitor.visit(tree)
                    imported_modules.update(visitor.imports)
                except SyntaxError as e:
                    print(f"Warning: Syntax error in file {file_path}: {e}", file=sys.stderr)
                except PermissionError as e:
                    print(f"Warning: Permission denied for file {file_path}: {e}", file=sys.stderr)
                except Exception as e:
                    print(f"Warning: Failed to parse file {file_path}: {e}", file=sys.stderr)

    # 4. 剔除标准库与本地库
    stdlib = getattr(sys, 'stdlib_module_names', set())
    if not stdlib:
        stdlib = STD_LIBS
    else:
        stdlib = stdlib.union(STD_LIBS)
        
    stdlib = stdlib.union(sys.builtin_module_names)
    
    # 动态排除项目自身的模块/包名，防止自我扫描干扰
    project_name = project_path.name
    ignored_project_names = {
        '', 
        project_name, 
        project_name.replace('-', '_'),
        normalize_package_name(project_name)
    }
        
    filtered_imports = set()
    for imp in imported_modules:
        first_comp = imp.split('.')[0]
        if (first_comp not in stdlib and 
            first_comp not in local_files and 
            first_comp not in ignored_project_names):
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
        normalized_pypi_name = normalize_package_name(pypi_name)
        
        if normalized_pypi_name in grouped_results:
            grouped_results[normalized_pypi_name]["import_names"].add(import_name)
            continue
            
        installed_version = None
        status = "not_installed"
        
        try:
            installed_version = importlib.metadata.version(pypi_name)
            status = "installed"
        except importlib.metadata.PackageNotFoundError:
            try:
                installed_version = importlib.metadata.version(normalized_pypi_name)
                status = "installed"
                pypi_name = normalized_pypi_name
            except importlib.metadata.PackageNotFoundError:
                try:
                    installed_version = importlib.metadata.version(import_name)
                    status = "installed"
                    pypi_name = import_name
                except importlib.metadata.PackageNotFoundError:
                    try:
                        normalized_import_name = normalize_package_name(import_name)
                        installed_version = importlib.metadata.version(normalized_import_name)
                        status = "installed"
                        pypi_name = normalized_import_name
                    except importlib.metadata.PackageNotFoundError:
                        pass
                
        grouped_results[normalized_pypi_name] = {
            "import_names": {import_name},
            "pypi_name": pypi_name,
            "version": installed_version,
            "status": status
        }
        
    results = []
    for normalized_pypi_name, info in grouped_results.items():
        results.append({
            "import_name": ", ".join(sorted(list(info["import_names"]))),
            "pypi_name": info["pypi_name"],
            "version": info["version"],
            "status": info["status"]
        })
        
    return results

def parse_requirements_file(file_path, visited=None):
    """
    Parses a requirements.txt file and returns a dictionary of package names mapped to lines.
    Supports recursive parsing of include files (-r <file>).
    """
    if visited is None:
        visited = set()
        
    packages = {}
    file_path = os.path.abspath(file_path)
    if file_path in visited or not os.path.exists(file_path):
        return packages
    visited.add(file_path)
    
    base_dir = os.path.dirname(file_path)
    
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            line_strip = line.strip()
            if not line_strip or line_strip.startswith('#'):
                continue
            
            # Handle recursive inclusion: -r filename or --requirement filename
            if line_strip.startswith('-r ') or line_strip.startswith('--requirement '):
                parts = line_strip.split(None, 1)
                if len(parts) == 2:
                    sub_file = parts[1].strip()
                    sub_path = os.path.join(base_dir, sub_file)
                    packages.update(parse_requirements_file(sub_path, visited))
                continue
                
            # Skip other options like -c, -f, -i, --index-url etc.
            if line_strip.startswith('-'):
                if line_strip.startswith('-e ') or line_strip.startswith('--editable '):
                    pkg_line = line_strip.split(None, 1)[1].strip()
                else:
                    continue
            else:
                pkg_line = line_strip

            # Extract package name
            pkg_name = None
            
            # Case 4: Egg fragment in VCS/URL dependencies (e.g. #egg=requests)
            if '#egg=' in pkg_line:
                egg_part = pkg_line.split('#egg=', 1)[1]
                pkg_name = re.split(r'[;&]', egg_part)[0].strip()
            
            # Case 5: Direct reference URL (PEP 508) (e.g. requests @ https://...)
            elif ' @ ' in pkg_line:
                pkg_name = pkg_line.split(' @ ', 1)[0].strip()
                
            else:
                # Standard format
                parts = pkg_line.split(';', 1)
                main_part = parts[0].strip()
                main_part = re.split(r'==|>=|<=|>|<|~=|!=', main_part)[0].strip()
                
                # Strip extras if present
                if '[' in main_part:
                    main_part = main_part.split('[', 1)[0].strip()
                    
                pkg_name = main_part
            
            if pkg_name:
                norm_name = normalize_package_name(pkg_name)
                packages[norm_name] = {
                    "raw": line_strip,
                    "name": pkg_name
                }
    return packages
