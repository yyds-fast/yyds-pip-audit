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
@click.option('-o', '--output', type=click.Path(writable=True), help="将依赖输出保存到指定文件 (例如 requirements.txt)")
@click.option('-f', '--format', 'output_format', type=click.Choice(['text', 'requirements', 'json']), default='text', help="依赖输出的格式格式: text (终端表格), requirements (标准依赖), json (JSON 数据)")
@click.option('-e', '--exclude', multiple=True, help="要忽略的额外目录名称 (可多次指定)")
@click.option('-c', '--check', type=click.Path(exists=True, dir_okay=False), help="审计对比指定的 requirements 文件，分析缺失和多余依赖")
@click.version_option(version=__version__, prog_name=__title__)
def main(directory, output, output_format, exclude, check):
    """
    yyds-pip-audit: 极速且精准的 Python 项目导入依赖审计及 PyPI 包映射工具。
    
    默认扫描当前目录或指定目录下的 Python 文件，解析所有第三方包的导入，
    并自动关联本地环境的版本。
    """
    # Resolve directory path
    directory_path = os.path.abspath(directory)
    
    # Audit dependencies and measure duration
    start_time = time.perf_counter()
    try:
        results = audit_dependencies(directory_path, exclude_dirs=exclude)
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
            console.print(f"[green]JSON 审计结果已成功写入到 {output}[/green]")
        else:
            print(formatted_content)
            
    elif output_format == 'requirements':
        lines = []
        for item in results:
            if item['status'] == 'installed':
                lines.append(f"{item['pypi_name']}=={item['version']}")
            else:
                lines.append(f"{item['pypi_name']} # 本地未安装")
        
        formatted_content = "\n".join(lines) + "\n"
        if output:
            with open(output, 'w', encoding='utf-8') as f:
                f.write(formatted_content)
            console.print(f"[green]依赖列表已成功导出到 {output}[/green]")
        else:
            print(formatted_content, end='')
            
    else:  # 'text' format
        # Show beautiful Rich outputs
        title_panel = Panel(
            f"[bold green]yyds-pip-audit v{__version__}[/bold green]\n"
            f"[dim]项目路径: {directory_path}\n"
            f"分析耗时: {duration:.3f} 秒[/dim]",
            title="🔍 依赖项分析与审计",
            expand=False
        )
        console.print(title_panel)
        
        if not results:
            console.print("[yellow]未检测到任何第三方依赖导入。[/yellow]")
        else:
            table = Table(show_header=True, header_style="bold magenta", box=None)
            table.add_column("导入名称", style="cyan")
            table.add_column("PyPI 包名称", style="green")
            table.add_column("本地版本", style="yellow")
            table.add_column("状态", style="bold")
            
            for item in results:
                status_str = "[green]已安装[/green]" if item['status'] == 'installed' else "[red]未安装[/red]"
                ver_str = item['version'] if item['version'] else "-"
                table.add_row(item['import_name'], item['pypi_name'], ver_str, status_str)
                
            console.print(table)
            
        if check:
            console.print("\n[bold blue]📋 Requirements.txt 对比审计结果[/bold blue]")
            console.print(f"[dim]对比文件: {os.path.abspath(check)}[/dim]\n")
            
            # Print missing
            if missing_in_reqs:
                console.print("[bold red]❌ 缺失的依赖 (代码中已导入，但未记录在 requirements 中):[/bold red]")
                for item in missing_in_reqs:
                    ver_suffix = f" (本地版本: {item['version']})" if item['version'] else ""
                    console.print(f"  • [red]{item['pypi_name']}[/red] [dim](由 import {item['import_name']} 引入){ver_suffix}[/dim]")
            else:
                console.print("[green]✔ 没发现缺失依赖 (所有导入都在 requirements 中记录)[/green]")
                
            # Print unused
            if unused_in_reqs:
                console.print("\n[bold yellow]⚠️ 未使用的依赖 (requirements 中记录了，但代码中没有导入):[/bold yellow]")
                for item in unused_in_reqs:
                    console.print(f"  • [yellow]{item['raw']}[/yellow]")
            else:
                console.print("\n[green]✔ 没发现多余依赖 (所有记录均被代码导入)[/green]")

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
            console.print(f"\n[green]✔ 依赖列表成功导出到 {output}[/green]")

if __name__ == "__main__":
    main()
