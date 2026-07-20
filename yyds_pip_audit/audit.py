# -*- coding:utf-8 -*-

import ast
import os
import re
import sys
import tokenize
from collections import defaultdict
from importlib import metadata
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from pathspec import PathSpec

try:
    from pathspec import GitIgnoreSpec
except ImportError:  # pragma: no cover - compatibility with older pathspec
    GitIgnoreSpec = None

# Default directories to ignore during traversal
DEFAULT_EXCLUDES = {
    '.venv', 'venv', 'env', '.env', '__pycache__', '.git', '.idea',
    'build', 'dist', 'node_modules', '.pytest_cache', '.tox',
    '.mypy_cache', '.hg', '.svn', 'egg-info',
    'htmlcov',
}

def normalize_package_name(name):
    """
    Normalize package name according to PEP 503.
    Lowers the name and replaces any sequence of ., _, - with a single -.
    """
    if not name:
        return ""
    return re.sub(r'[-_.]+', '-', name).lower()

class ImportVisitor(ast.NodeVisitor):
    """
    Optimized AST visitor that extracts absolute imports and static dynamic imports.
    """
    def __init__(self):
        self.imports = set()
        self.importlib_aliases = {'importlib'}
        self.import_module_aliases = set()

    def visit_Module(self, node):
        # Collect aliases before visiting calls. A function can reference an alias
        # imported later in the module, so relying on traversal order would miss it.
        for child in ast.walk(node):
            if isinstance(child, ast.Import):
                for alias in child.names:
                    if alias.name == 'importlib':
                        self.importlib_aliases.add(alias.asname or alias.name)
            elif isinstance(child, ast.ImportFrom):
                if child.level == 0 and child.module == 'importlib':
                    for alias in child.names:
                        if alias.name == 'import_module':
                            self.import_module_aliases.add(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_Import(self, node):
        for alias in node.names:
            self.imports.add(alias.name)
            if alias.name == 'importlib':
                self.importlib_aliases.add(alias.asname or alias.name)

    def visit_ImportFrom(self, node):
        if node.level == 0 and node.module:
            for alias in node.names:
                # Store full import path for namespace matching (e.g. google.cloud.storage)
                self.imports.add(f"{node.module}.{alias.name}")
                if node.module == 'importlib' and alias.name == 'import_module':
                    self.import_module_aliases.add(alias.asname or alias.name)

    def visit_Call(self, node):
        # Handle importlib.import_module('module_name')
        if isinstance(node.func, ast.Attribute):
            if (isinstance(node.func.value, ast.Name) and 
                node.func.value.id in self.importlib_aliases and
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
        elif (isinstance(node.func, ast.Name) and
              (node.func.id == '__import__' or node.func.id in self.import_module_aliases)):
            if node.args:
                val = None
                if isinstance(node.args[0], ast.Constant):
                    val = node.args[0].value
                elif hasattr(ast, 'Str') and isinstance(node.args[0], ast.Str):
                    val = node.args[0].s
                if isinstance(val, str):
                    self.imports.add(val)
        
        self.generic_visit(node)

def _read_gitignore_lines(project_dir):
    gitignore_path = Path(project_dir) / '.gitignore'
    if not gitignore_path.is_file():
        return []

    try:
        return gitignore_path.read_text(encoding='utf-8', errors='ignore').splitlines()
    except OSError as exc:
        print(f"Warning: Failed to read {gitignore_path}: {exc}", file=sys.stderr)
        return []


def parse_gitignore(project_dir):
    """
    Parses .gitignore file in project_dir and returns a list of patterns to exclude.
    """
    patterns = []
    for line in _read_gitignore_lines(project_dir):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        # Preserve the historical public return value. Matching itself is done
        # by PathSpec using the original lines in _build_gitignore_spec().
        if line.endswith('/'):
            line = line[:-1]
        patterns.append(line.replace('\\', '/'))
    return patterns


def _build_gitignore_spec(project_dir):
    """Build a matcher implementing Git's wildmatch and negation rules."""
    lines = _read_gitignore_lines(project_dir)
    if GitIgnoreSpec is not None:
        return GitIgnoreSpec.from_lines(lines)
    return PathSpec.from_lines('gitwildmatch', lines)

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
    if dir_name in exclude_base_names or dir_name.endswith('.egg-info'):
        return True
    
    # Check if absolute path matches or starts with any of the excluded absolute paths
    try:
        dir_abs = Path(dir_full_path).resolve()
        for p in exclude_absolute_paths:
            if dir_abs == p or p in dir_abs.parents:
                return True
    except OSError:
        return True
        
    return False

def _module_paths_from_distribution(dist):
    """Extract importable Python module paths from distribution RECORD data."""
    try:
        dist_files = tuple(dist.files or ())
    except Exception:
        return []

    module_paths = []
    for file_path in dist_files:
        path_str = str(file_path).replace('\\', '/')
        if not path_str.endswith('.py'):
            continue

        parts = list(Path(path_str).parts)
        if any(
            part.startswith('.') or part.endswith(('.dist-info', '.egg-info'))
            for part in parts
        ):
            continue

        if parts[-1] == '__init__.py':
            parts.pop()
        else:
            parts[-1] = Path(parts[-1]).stem

        if parts and all(part.isidentifier() for part in parts):
            module_paths.append('.'.join(parts))

    return module_paths


def build_local_import_mapping(imported_top_levels=None, include_sources=False):
    """
    Stream-scans metadata of all installed distributions in the environment
    and builds a reverse mapping: [imported module name -> PyPI package name].
    Supports namespace packages using dist.files matching.
    """
    mapping = {}
    deferred_distributions = []
    
    # Traverse all installed distributions in the active python environment
    for dist in metadata.distributions():
        try:
            # Metadata keys can be normalized
            package_name = dist.metadata.get('Name') or dist.name
            if not package_name:
                continue
        except Exception:
            continue

        # Get top-level names for this package to check if it is relevant.
        declared_top_levels = []
        try:
            top_txt = dist.read_text('top_level.txt')
            if top_txt:
                declared_top_levels = [
                    line.strip()
                    for line in top_txt.splitlines()
                    if line.strip() and not line.startswith('#')
                ]
        except Exception:
            pass

        top_levels = declared_top_levels or [
            package_name.lower().replace('-', '_'),
            package_name,
        ]

        # Optimization: skip packages that are not imported by the project at all
        if (
            imported_top_levels is not None
            and not any(top_level in imported_top_levels for top_level in top_levels)
        ):
            # A distribution without top_level.txt can expose a completely
            # different import name. Defer its RECORD scan until we know that
            # an imported top-level remains unresolved.
            if not declared_top_levels:
                deferred_distributions.append((dist, package_name))
            continue

        # Try mapping files first (best support for namespaces)
        module_paths = _module_paths_from_distribution(dist)
        for module_path in module_paths:
            mapping[module_path] = package_name

        if not module_paths:
            for tl in top_levels:
                mapping[tl] = package_name

    mapping_sources = {module_path: 'metadata' for module_path in mapping}

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
        "onnxruntime": "onnxruntime",
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
        "tomli": "tomli",
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
            mapping_sources[k] = 'fallback'

    # Resolve only genuinely unknown imports through the expensive RECORD path.
    # Known fallbacks avoid a full environment scan, while unknown non-standard
    # package names can still be proven from installed distribution metadata.
    if imported_top_levels is not None:
        mapped_top_levels = {module_path.split('.')[0] for module_path in mapping}
        unresolved_top_levels = set(imported_top_levels) - mapped_top_levels
        if unresolved_top_levels:
            for dist, package_name in deferred_distributions:
                module_paths = _module_paths_from_distribution(dist)
                distribution_top_levels = {
                    module_path.split('.')[0] for module_path in module_paths
                }
                if not distribution_top_levels.intersection(unresolved_top_levels):
                    continue
                for module_path in module_paths:
                    mapping[module_path] = package_name
                    mapping_sources[module_path] = 'metadata'

    if include_sources:
        return mapping, mapping_sources
    return mapping

def _is_within(path, parent):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _resolve_source_roots(project_path, source_roots=None):
    """Return import roots used to identify project-local modules."""
    roots = [project_path]
    if isinstance(source_roots, (str, os.PathLike)):
        configured_roots = [source_roots]
    else:
        configured_roots = list(source_roots or [])

    # src/ is the dominant modern packaging layout, so recognize it without
    # requiring configuration while retaining flat-layout behavior.
    if not configured_roots and (project_path / 'src').is_dir():
        configured_roots.append('src')

    for root in configured_roots:
        candidate = Path(root)
        if not candidate.is_absolute():
            candidate = project_path / candidate
        candidate = candidate.resolve()
        if not _is_within(candidate, project_path):
            raise ValueError(f"Source root must stay inside the project: {root}")
        if not candidate.is_dir():
            raise ValueError(f"Source root does not exist or is not a directory: {root}")
        if candidate not in roots:
            roots.append(candidate)

    return roots


def _prepare_exclusions(project_path, exclude_dirs=None):
    base_names = set(DEFAULT_EXCLUDES)
    relative_paths = set()
    absolute_paths = set()

    for raw_item in exclude_dirs or ():
        item = str(raw_item).strip()
        if not item:
            continue

        item_path = Path(item)
        if item_path.is_absolute():
            absolute_paths.add(item_path.resolve())
            continue

        normalized = item.replace('\\', '/')
        while normalized.startswith('./'):
            normalized = normalized[2:]
        normalized = normalized.strip('/')
        if '/' in normalized:
            relative_paths.add(normalized)
        else:
            base_names.add(normalized)

    return base_names, relative_paths, absolute_paths


def _matches_relative_exclusion(relative_path, excluded_paths):
    path_str = relative_path.as_posix().strip('/')
    return any(
        path_str == excluded or path_str.startswith(f"{excluded}/")
        for excluded in excluded_paths
    )


def _index_local_modules(python_files, project_path):
    """Index importable names per directory without globally conflating stems."""
    entries = defaultdict(set)

    for file_path in python_files:
        if file_path.name != '__init__.py' and file_path.stem.isidentifier():
            entries[file_path.parent].add(file_path.stem)

        current = file_path.parent
        while current != project_path and _is_within(current, project_path):
            if current.name.isidentifier():
                entries[current.parent].add(current.name)
            current = current.parent

    return entries


def extract_imports(project_dir, exclude_dirs=None, source_roots=None):
    """
    扫描 project_dir，解析本地模块、标准库模块，并提取第三方导入模块名称。
    支持 .gitignore 自动集成与绝对/相对路径匹配。
    """
    project_path = Path(project_dir).resolve()
    
    import_roots = _resolve_source_roots(project_path, source_roots)
    exclude_base_names, exclude_relative_paths, exclude_absolute_paths = (
        _prepare_exclusions(project_path, exclude_dirs)
    )
    gitignore_spec = _build_gitignore_spec(project_path)

    imported_occurrences = []
    python_files = []

    # os.walk uses scandir internally. Directories are pruned before files are
    # parsed, while negated Git rules remain respected by PathSpec.
    for root, dirs, files in os.walk(project_path):
        root_path = Path(root)
        pruned_dirs = []
        for d in dirs:
            dir_path = root_path / d
            relative_dir = dir_path.relative_to(project_path)
            relative_dir_str = f"{relative_dir.as_posix()}/"

            if d in exclude_base_names or d.endswith('.egg-info'):
                continue
            if _matches_relative_exclusion(relative_dir, exclude_relative_paths):
                continue
            if gitignore_spec.match_file(relative_dir_str):
                continue

            try:
                resolved_dir = dir_path.resolve()
            except (OSError, RuntimeError):
                continue
            if not _is_within(resolved_dir, project_path):
                continue
            if any(
                resolved_dir == excluded or _is_within(resolved_dir, excluded)
                for excluded in exclude_absolute_paths
            ):
                continue
            pruned_dirs.append(d)
            
        # 原地剪枝
        dirs[:] = pruned_dirs
        
        for file in files:
            # Avoid resolving and stat-ing non-Python assets in large projects.
            if not file.endswith('.py'):
                continue

            file_path = root_path / file
            relative_file = file_path.relative_to(project_path)
            if file in exclude_base_names:
                continue
            if _matches_relative_exclusion(relative_file, exclude_relative_paths):
                continue
            if gitignore_spec.match_file(relative_file.as_posix()):
                continue

            try:
                resolved_file = file_path.resolve()
            except (OSError, RuntimeError) as exc:
                print(f"Warning: Failed to resolve file {file_path}: {exc}", file=sys.stderr)
                continue
            if not _is_within(resolved_file, project_path):
                print(f"Warning: Skipping Python symlink outside project: {file_path}", file=sys.stderr)
                continue
            if any(
                resolved_file == excluded or _is_within(resolved_file, excluded)
                for excluded in exclude_absolute_paths
            ):
                continue

            python_files.append(file_path)

            try:
                if file_path.stat().st_size > 2 * 1024 * 1024:
                    print(f"Warning: Skipping Python file larger than 2 MiB: {file_path}", file=sys.stderr)
                    continue

                # tokenize.open honors PEP 263 encoding declarations.
                with tokenize.open(str(file_path)) as source_file:
                    content = source_file.read()

                tree = ast.parse(content, filename=str(file_path))
                visitor = ImportVisitor()
                visitor.visit(tree)
                imported_occurrences.extend(
                    (import_name, file_path) for import_name in visitor.imports
                )
            except SyntaxError as exc:
                print(f"Warning: Syntax error in file {file_path}: {exc}", file=sys.stderr)
            except PermissionError as exc:
                print(f"Warning: Permission denied for file {file_path}: {exc}", file=sys.stderr)
            except (OSError, UnicodeError) as exc:
                print(f"Warning: Failed to read file {file_path}: {exc}", file=sys.stderr)

    # Filter standard-library and project-local imports after the complete local
    # module index is available.
    stdlib = set(sys.stdlib_module_names)
    stdlib.update(sys.builtin_module_names)

    local_entries = _index_local_modules(python_files, project_path)
    
    # 动态排除项目自身的模块/包名，防止自我扫描干扰
    project_name = project_path.name
    ignored_project_names = {
        '', 
        project_name, 
        project_name.replace('-', '_'),
        normalize_package_name(project_name)
    }
        
    filtered_imports = set()
    for imp, source_file in imported_occurrences:
        first_comp = imp.split('.')[0]
        is_local = first_comp in local_entries[source_file.parent]
        if not is_local:
            is_local = any(first_comp in local_entries[root] for root in import_roots)

        if (
            first_comp not in stdlib
            and not is_local
            and first_comp not in ignored_project_names
        ):
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


def resolve_pypi_details(import_path, import_to_pypi, mapping_sources):
    """Resolve a package and expose whether metadata or a fallback proved it."""
    parts = import_path.split('.')
    while parts:
        candidate = '.'.join(parts)
        if candidate in import_to_pypi:
            return (
                import_to_pypi[candidate],
                candidate,
                mapping_sources.get(candidate, 'metadata'),
            )
        parts.pop()

    first_comp = import_path.split('.')[0]
    return first_comp, first_comp, 'unresolved'

def audit_dependencies(project_dir, exclude_dirs=None, source_roots=None):
    """
    Audits imports in the project_dir and maps them to PyPI package names and versions.
    Groups results by PyPI package name to handle namespace packages and duplicate submodules.
    """
    imported_mods = extract_imports(project_dir, exclude_dirs, source_roots)
    imported_top_levels = {mod.split('.')[0] for mod in imported_mods}
    import_to_pypi, mapping_sources = build_local_import_mapping(
        imported_top_levels,
        include_sources=True,
    )
    
    grouped_results = {}
    for mod in imported_mods:
        pypi_name, import_name, resolution = resolve_pypi_details(
            mod,
            import_to_pypi,
            mapping_sources,
        )
        normalized_pypi_name = normalize_package_name(pypi_name)
        
        if normalized_pypi_name in grouped_results:
            grouped_results[normalized_pypi_name]["import_names"].add(import_name)
            resolution_rank = {'unresolved': 0, 'fallback': 1, 'metadata': 2}
            if resolution_rank[resolution] > resolution_rank[
                grouped_results[normalized_pypi_name]["resolution"]
            ]:
                grouped_results[normalized_pypi_name]["resolution"] = resolution
            continue
            
        installed_version = None
        status = "not_installed"
        
        try:
            installed_version = metadata.version(pypi_name)
            status = "installed"
        except metadata.PackageNotFoundError:
            try:
                installed_version = metadata.version(normalized_pypi_name)
                status = "installed"
                pypi_name = normalized_pypi_name
            except metadata.PackageNotFoundError:
                try:
                    installed_version = metadata.version(import_name)
                    status = "installed"
                    pypi_name = import_name
                except metadata.PackageNotFoundError:
                    try:
                        normalized_import_name = normalize_package_name(import_name)
                        installed_version = metadata.version(normalized_import_name)
                        status = "installed"
                        pypi_name = normalized_import_name
                    except metadata.PackageNotFoundError:
                        pass
                
        grouped_results[normalized_pypi_name] = {
            "import_names": {import_name},
            "pypi_name": pypi_name,
            "version": installed_version,
            "status": status,
            "resolution": resolution,
        }
        
    results = []
    for info in grouped_results.values():
        results.append({
            "import_name": ", ".join(sorted(list(info["import_names"]))),
            "pypi_name": info["pypi_name"],
            "version": info["version"],
            "status": info["status"],
            "resolution": info["resolution"],
        })
        
    return results

def _requirement_logical_lines(file_obj):
    """Join pip-style line continuations while preserving the original text."""
    pending = ''
    for physical_line in file_obj:
        stripped = physical_line.rstrip('\r\n')
        if stripped.rstrip().endswith('\\'):
            pending += stripped.rstrip()[:-1] + ' '
            continue
        yield pending + stripped
        pending = ''
    if pending:
        yield pending


def _included_requirement_path(line):
    for prefix in ('-r ', '--requirement '):
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    if line.startswith('-r') and len(line) > 2:
        return line[2:].strip()
    if line.startswith('--requirement='):
        return line.split('=', 1)[1].strip()
    return None


def parse_requirements_file(file_path, visited=None, evaluate_markers=False):
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
        for line in _requirement_logical_lines(f):
            line_strip = line.strip()
            if not line_strip or line_strip.startswith('#'):
                continue

            directive_line = re.sub(r'\s+#.*$', '', line_strip).strip()

            included_path = _included_requirement_path(directive_line)
            if included_path:
                sub_path = os.path.join(base_dir, included_path)
                packages.update(
                    parse_requirements_file(
                        sub_path,
                        visited,
                        evaluate_markers=evaluate_markers,
                    )
                )
                continue

            # Skip other options like -c, -f, -i, --index-url etc.
            if line_strip.startswith('-'):
                if line_strip.startswith('-e ') or line_strip.startswith('--editable '):
                    pkg_line = line_strip.split(None, 1)[1].strip()
                elif line_strip.startswith('--editable='):
                    pkg_line = line_strip.split('=', 1)[1].strip()
                else:
                    continue
            else:
                pkg_line = line_strip

            # Remove pip hashes and comments, but preserve URL fragments such as
            # #egg=package which have no preceding whitespace.
            pkg_line = re.sub(r'\s+--hash(?:=|\s+)\S+', '', pkg_line).strip()
            pkg_line = re.sub(r'\s+#.*$', '', pkg_line).strip()

            pkg_name = None
            requirement = None
            if '#egg=' in pkg_line:
                egg_part = pkg_line.split('#egg=', 1)[1]
                pkg_name = re.split(r'[;&]', egg_part)[0].strip()
            else:
                try:
                    requirement = Requirement(pkg_line)
                    pkg_name = requirement.name
                except InvalidRequirement:
                    # Bare VCS/local paths without #egg do not provide a safe,
                    # standardized distribution name and are intentionally skipped.
                    continue

            if (
                evaluate_markers
                and requirement is not None
                and requirement.marker is not None
                and not requirement.marker.evaluate()
            ):
                continue

            if pkg_name:
                norm_name = normalize_package_name(pkg_name)
                packages[norm_name] = {
                    "raw": line_strip,
                    "name": pkg_name
                }
    return packages
