# -*- coding:utf-8 -*-

import sys
import os
import json
import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

import time
from .__version__ import __version__, __title__, __description__
from .audit import audit_dependencies, parse_requirements_file

console = Console()

@click.command()
@click.argument('directory', type=click.Path(exists=True, file_okay=False, dir_okay=True), default=".")
@click.option('-o', '--output', type=click.Path(writable=True), help="Save dependency output to specified file (e.g. requirements.txt)")
@click.option('-f', '--format', 'output_format', type=click.Choice(['text', 'requirements', 'json']), default='text', help="Format of the dependency output: text (terminal table), requirements (standard dependencies), json (JSON data)")
@click.option('-e', '--exclude', multiple=True, help="Extra directory names to exclude (can be specified multiple times)")
@click.option('-c', '--check', type=click.Path(exists=True, dir_okay=False), help="Audit and compare against specified requirements file to analyze missing and unused dependencies")
@click.version_option(version=__version__, prog_name=__title__)
def main(directory, output, output_format, exclude, check):
    """
    yyds-pip-audit: A fast and precise Python project import dependency auditing and PyPI mapping tool.
    
    Scans the specified directory (defaults to current directory) for Python files,
    extracts all third-party package imports, and associates them with installed local versions.
    """
    # Resolve directory path
    directory_path = os.path.abspath(directory)
    
    # Process comma-separated excludes
    exclude_list = []
    for item in exclude:
        exclude_list.extend([x.strip() for x in item.split(',') if x.strip()])
    
    # Audit dependencies and measure duration
    start_time = time.perf_counter()
    try:
        results = audit_dependencies(directory_path, exclude_dirs=exclude_list)
    except Exception as e:
        console.print(f"[red]Error during dependency auditing: {e}[/red]", err=True)
        sys.exit(1)
    duration = time.perf_counter() - start_time

    # Perform comparison check if requested
    check_results = None
    if check:
        reqs = parse_requirements_file(check)
        audited_pypi_names = {item['pypi_name'].lower().replace('_', '-') for item in results}
        
        missing_in_reqs = []
        unused_in_reqs = []
        
        # 1. Missing in requirements.txt (imported but not in requirements)
        for item in results:
            pypi_norm = item['pypi_name'].lower().replace('_', '-')
            if pypi_norm not in reqs:
                missing_in_reqs.append(item)
                
        # 2. Unused in requirements.txt (in requirements but not imported)
        for norm_name, req_info in reqs.items():
            if norm_name not in audited_pypi_names:
                unused_in_reqs.append(req_info)
                
        check_results = {
            "missing": missing_in_reqs,
            "unused": unused_in_reqs
        }

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
            with open(output, 'w', encoding='utf-8') as f:
                f.write(formatted_content)
            console.print(f"[green]JSON audit results successfully saved to {output}[/green]")
        else:
            print(formatted_content)
            
    elif output_format == 'requirements':
        lines = []
        for item in results:
            if item['status'] == 'installed':
                lines.append(f"{item['pypi_name']}=={item['version']}")
            else:
                lines.append(f"{item['pypi_name']}")
        
        formatted_content = "\n".join(lines) + "\n"
        if output:
            with open(output, 'w', encoding='utf-8') as f:
                f.write(formatted_content)
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
            table.add_column("Import Name", style="cyan")
            table.add_column("PyPI Package", style="green")
            table.add_column("Local Version", style="yellow")
            table.add_column("Status", style="bold")
            
            for item in results:
                status_str = "[green]Installed[/green]" if item['status'] == 'installed' else "[red]Not Installed[/red]"
                ver_str = item['version'] if item['version'] else "-"
                table.add_row(item['import_name'], item['pypi_name'], ver_str, status_str)
                
            console.print(table)
            
        if check:
            console.print("\n[bold blue]📋 Requirements.txt Audit & Comparison Results[/bold blue]")
            console.print(f"[dim]Comparison File: {os.path.abspath(check)}[/dim]\n")
            
            # Print missing
            if missing_in_reqs:
                console.print("[bold red]❌ Missing Dependencies (imported in code but not registered in requirements):[/bold red]")
                for item in missing_in_reqs:
                    ver_suffix = f" (local version: {item['version']})" if item['version'] else ""
                    console.print(f"  • [red]{item['pypi_name']}[/red] [dim](introduced by import {item['import_name']}){ver_suffix}[/dim]")
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
            lines = []
            for item in results:
                if item['status'] == 'installed':
                    lines.append(f"{item['pypi_name']}=={item['version']}")
                else:
                    lines.append(f"{item['pypi_name']}")
            with open(output, 'w', encoding='utf-8') as f:
                f.write("\n".join(lines) + "\n")
            console.print(f"\n[green]✔ Dependencies successfully exported to {output}[/green]")

if __name__ == "__main__":
    main()
