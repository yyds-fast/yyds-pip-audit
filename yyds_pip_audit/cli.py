# -*- coding:utf-8 -*-

import json
import os
import tempfile
import time
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .__version__ import __title__, __version__
from .audit import audit_dependencies, normalize_package_name, parse_requirements_file

try:
    import tomllib
except ImportError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib

console = Console()

def load_config_from_toml(project_dir):
    """
    Loads configuration from pyproject.toml if present.
    Uses the standard TOML parser or its compatibility backport.
    """
    toml_path = Path(project_dir) / 'pyproject.toml'
    if not toml_path.exists():
        return {}

    try:
        with toml_path.open('rb') as config_file:
            data = tomllib.load(config_file)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise click.ClickException(
            f"Failed to load configuration {toml_path}: {exc}"
        ) from exc

    config = data.get('tool', {}).get('yyds-pip-audit', {})
    if not isinstance(config, dict):
        raise click.ClickException(
            "Configuration section [tool.yyds-pip-audit] must be a TOML table"
        )
    return config

def format_display_imports(import_name_str, max_items=3):
    if not import_name_str:
        return ""
    parts = [p.strip() for p in import_name_str.split(',') if p.strip()]
    if len(parts) > max_items:
        return ", ".join(parts[:max_items]) + f" ... (+{len(parts) - max_items} more)"
    return import_name_str


def _config_string_list(config, *keys):
    value = []
    for key in keys:
        if key in config:
            value = config[key]
            break
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    raise click.ClickException(
        f"Configuration value {keys[0]} must be a string or an array of strings"
    )


def requirements_lines(results, include_unresolved=False):
    """Render safe requirement lines and return unresolved packages skipped."""
    lines = []
    skipped = []
    for item in results:
        if item.get('resolution') == 'unresolved' and not include_unresolved:
            skipped.append(item['pypi_name'])
            continue
        if item['status'] == 'installed':
            lines.append(f"{item['pypi_name']}=={item['version']}")
        else:
            lines.append(item['pypi_name'])
    return lines, skipped


def _is_within(path, parent):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def resolve_config_output_path(project_dir, configured_output):
    """Resolve config-controlled output without allowing writes outside a project."""
    project_path = Path(project_dir).resolve()
    output_path = Path(configured_output).expanduser()
    if not output_path.is_absolute():
        output_path = project_path / output_path
    output_path = output_path.resolve()

    if not _is_within(output_path, project_path):
        raise click.ClickException(
            "The output path from pyproject.toml must stay inside the audited project. "
            "Use --output explicitly to write elsewhere."
        )
    return str(output_path)


def write_text_atomic(output_path, content):
    """Atomically replace a text output file to avoid partial audit reports."""
    target = Path(output_path).expanduser()
    parent = target.parent.resolve()
    if not parent.is_dir():
        raise click.ClickException(f"Output directory does not exist: {parent}")
    if target.exists() and target.is_dir():
        raise click.ClickException(f"Output path is a directory: {target}")

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w',
            encoding='utf-8',
            dir=str(parent),
            prefix=f".{target.name}.",
            suffix='.tmp',
            delete=False,
        ) as temp_file:
            temp_file.write(content)
            temp_path = Path(temp_file.name)
        os.replace(str(temp_path), str(target))
    except OSError as exc:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise click.ClickException(f"Failed to write output file {target}: {exc}") from exc

@click.command()
@click.argument('directory', type=click.Path(exists=True, file_okay=False, dir_okay=True), default=".")
@click.option('-o', '--output', type=click.Path(writable=True, dir_okay=False), help="Save dependency output to specified file (e.g. requirements.txt)")
@click.option('-f', '--format', 'output_format', type=click.Choice(['text', 'requirements', 'json']), default=None, help="Format of the dependency output: text (terminal table), requirements (standard dependencies), json (JSON data)")
@click.option('-e', '--exclude', multiple=True, help="Extra directory names to exclude (can be specified multiple times)")
@click.option('--source-root', multiple=True, help="Project import root used to identify local packages (e.g. src)")
@click.option('-c', '--check', type=click.Path(exists=True, dir_okay=False), help="Audit and compare against specified requirements file to analyze missing and unused dependencies")
@click.option('--fail-on', type=click.Choice(['none', 'missing', 'unused', 'any']), default=None, help="Return exit code 1 when selected requirement issues are found")
@click.option(
    '--include-unresolved/--skip-unresolved',
    default=None,
    help="Include or skip unverified package guesses in requirements output",
)
@click.option(
    '--evaluate-markers/--ignore-markers',
    default=None,
    help="Select whether requirement markers are evaluated for this interpreter",
)
@click.version_option(version=__version__, prog_name=__title__)
def main(directory, output, output_format, exclude, source_root, check, fail_on, include_unresolved, evaluate_markers):
    """
    yyds-pip-audit: A fast and precise Python project import dependency auditing and PyPI mapping tool.
    
    Scans the specified directory (defaults to current directory) for Python files,
    extracts all third-party package imports, and associates them with installed local versions.
    """
    # Resolve directory path
    directory_path = os.path.abspath(directory)
    
    # Load configuration from pyproject.toml
    config = load_config_from_toml(directory_path)
    
    # CLI output can be explicit and external. Config-controlled output is
    # resolved relative to, and constrained within, the audited project.
    configured_output = config.get('output')
    if output is None and configured_output:
        if not isinstance(configured_output, str):
            raise click.ClickException("Configuration value output must be a string")
        output = resolve_config_output_path(directory_path, configured_output)

    output_format = output_format or config.get('format') or 'text'
    if not isinstance(output_format, str) or output_format not in {
        'text',
        'requirements',
        'json',
    }:
        raise click.ClickException(f"Unsupported output format in configuration: {output_format}")

    fail_on = fail_on or config.get('fail_on') or config.get('fail-on') or 'none'
    if not isinstance(fail_on, str) or fail_on not in {
        'none',
        'missing',
        'unused',
        'any',
    }:
        raise click.ClickException(f"Unsupported fail_on value in configuration: {fail_on}")

    configured_include_unresolved = config.get('include_unresolved', False)
    if not isinstance(configured_include_unresolved, bool):
        raise click.ClickException("Configuration value include_unresolved must be a boolean")
    if include_unresolved is None:
        include_unresolved = configured_include_unresolved

    configured_evaluate_markers = config.get('evaluate_markers', False)
    if not isinstance(configured_evaluate_markers, bool):
        raise click.ClickException("Configuration value evaluate_markers must be a boolean")
    if evaluate_markers is None:
        evaluate_markers = configured_evaluate_markers
    
    # Process and merge excludes from both CLI and pyproject.toml
    exclude_list = []
    for item in exclude:
        exclude_list.extend([x.strip() for x in item.split(',') if x.strip()])
    
    config_excludes = _config_string_list(config, 'exclude')
    for item in config_excludes:
        exclude_list.append(item.strip())

    configured_source_roots = _config_string_list(config, 'source_roots', 'source-roots')
    source_roots = list(source_root) if source_root else list(configured_source_roots)
    
    # Audit dependencies and measure duration
    start_time = time.perf_counter()
    try:
        results = audit_dependencies(
            directory_path,
            exclude_dirs=exclude_list,
            source_roots=source_roots,
        )
    except Exception as exc:
        raise click.ClickException(f"Error during dependency auditing: {exc}") from exc
    duration = time.perf_counter() - start_time

    # Perform comparison check if requested
    missing_in_reqs = []
    unused_in_reqs = []
    if check:
        try:
            reqs = parse_requirements_file(check, evaluate_markers=evaluate_markers)
        except OSError as exc:
            raise click.ClickException(
                f"Failed to read requirements file {check}: {exc}"
            ) from exc
        audited_pypi_names = {normalize_package_name(item['pypi_name']) for item in results}
        
        # 1. Missing in requirements.txt (imported but not in requirements)
        for item in results:
            pypi_norm = normalize_package_name(item['pypi_name'])
            if pypi_norm not in reqs:
                missing_in_reqs.append(item)
                
        # 2. Unused in requirements.txt (in requirements but not imported)
        for norm_name, req_info in reqs.items():
            if norm_name not in audited_pypi_names:
                unused_in_reqs.append(req_info)
                
    # Format output
    if output_format == 'json':
        output_data = {
            "project_dir": directory_path,
            "duration_seconds": round(duration, 4),
            "dependencies": results
        }
        if check:
            output_data["check"] = {
                "requirements_file": os.path.abspath(check),
                "missing": [item['pypi_name'] for item in missing_in_reqs],
                "unused": [item['name'] for item in unused_in_reqs]
            }
        
        formatted_content = json.dumps(output_data, indent=2, ensure_ascii=False)
        if output:
            write_text_atomic(output, formatted_content)
            console.print(f"[green]JSON audit results successfully saved to {output}[/green]")
        else:
            print(formatted_content)
            
    elif output_format == 'requirements':
        lines, skipped_unresolved = requirements_lines(results, include_unresolved)
        if skipped_unresolved:
            console.print(
                "[yellow]Skipped unresolved package guesses: "
                f"{', '.join(skipped_unresolved)}. Use --include-unresolved to export them.[/yellow]",
                err=True,
            )
        
        formatted_content = "\n".join(lines) + "\n"
        if output:
            write_text_atomic(output, formatted_content)
            console.print(f"[green]Dependencies list successfully exported to {output}[/green]")
        else:
            print(formatted_content, end='')
            
    else:  # 'text' format
        # Show beautiful Rich outputs
        title_panel = Panel(
            f"[bold green]yyds-pip-audit v{__version__}[/bold green]\n"
            f"[dim]Project Path: {directory_path}\n"
            f"Audit Time: {duration:.3f} seconds[/dim]",
            title="🔍 Dependency Analysis & Audit",
            expand=False
        )
        console.print(title_panel)
        
        if not results:
            console.print("[yellow]No third-party dependency imports detected.[/yellow]")
        else:
            table = Table(show_header=True, header_style="bold magenta", box=None)
            table.add_column("Import Name", style="cyan", max_width=45)
            table.add_column("PyPI Package", style="green")
            table.add_column("Local Version", style="yellow")
            table.add_column("Status", style="bold")
            table.add_column("Resolution", style="blue")
            
            for item in results:
                status_str = "[green]Installed[/green]" if item['status'] == 'installed' else "[red]Not Installed[/red]"
                ver_str = item['version'] if item['version'] else "-"
                display_imp = format_display_imports(item['import_name'])
                table.add_row(
                    display_imp,
                    item['pypi_name'],
                    ver_str,
                    status_str,
                    item.get('resolution', 'unknown').title(),
                )
                
            console.print(table)
            
        if check:
            console.print("\n[bold blue]📋 Requirements.txt Audit & Comparison Results[/bold blue]")
            console.print(f"[dim]Comparison File: {os.path.abspath(check)}[/dim]\n")
            
            # Print missing
            if missing_in_reqs:
                console.print("[bold red]❌ Missing Dependencies (imported in code but not registered in requirements):[/bold red]")
                for item in missing_in_reqs:
                    ver_suffix = f" (local version: {item['version']})" if item['version'] else ""
                    display_imp = format_display_imports(item['import_name'])
                    console.print(f"  • [red]{item['pypi_name']}[/red] [dim](introduced by import {display_imp}){ver_suffix}[/dim]")
            else:
                console.print("[green]✔ No missing dependencies found (all imports are registered in requirements)[/green]")
                
            # Print unused
            if unused_in_reqs:
                console.print("\n[bold yellow]⚠️ Unused Dependencies (registered in requirements but not imported in code):[/bold yellow]")
                for item in unused_in_reqs:
                    console.print(f"  • [yellow]{item['raw']}[/yellow]")
            else:
                console.print("\n[green]✔ No unused dependencies found (all requirements are imported in code)[/green]")

        if output:
            # Write default requirements file (even in text mode we support saving as requirements file)
            lines, skipped_unresolved = requirements_lines(results, include_unresolved)
            write_text_atomic(output, "\n".join(lines) + "\n")
            console.print(f"\n[green]✔ Dependencies successfully exported to {output}[/green]")
            if skipped_unresolved:
                console.print(
                    "[yellow]Skipped unresolved package guesses: "
                    f"{', '.join(skipped_unresolved)}[/yellow]"
                )

    should_fail = check and (
        (fail_on == 'missing' and missing_in_reqs)
        or (fail_on == 'unused' and unused_in_reqs)
        or (fail_on == 'any' and (missing_in_reqs or unused_in_reqs))
    )
    if should_fail:
        raise click.exceptions.Exit(1)

if __name__ == "__main__":
    main()
