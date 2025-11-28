"""Graph generation command implementation."""

import argparse
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

from spacesim2.cli.output import print_error, print_success


def add_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:  # type: ignore
    """Add the 'graph' dev subcommand parser.

    Args:
        subparsers: Subparsers to add this command to

    Returns:
        The created parser
    """
    parser = subparsers.add_parser(
        "graph",
        help="Generate commodity/process dependency graph",
        description="Convert YAML commodity/process definitions to Mermaid diagrams and render",
    )

    parser.add_argument(
        "--out",
        "-o",
        type=str,
        default=None,
        help="Save output to this base filename (no extension)",
    )
    parser.add_argument(
        "--format",
        "-f",
        type=str,
        choices=["svg", "png", "pdf"],
        default="svg",
        help="Output format (default: svg)",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open the output diagram after rendering",
    )

    parser.set_defaults(func=execute)
    return parser


def _load_yaml(file_path: Path) -> List[Dict[str, Any]]:
    """Load YAML file.

    Args:
        file_path: Path to YAML file

    Returns:
        Parsed YAML data
    """
    with open(file_path, "r") as f:
        return yaml.safe_load(f)  # type: ignore


def _generate_mermaid_things(things: List[Dict[str, Any]]) -> Tuple[List[str], Dict[str, str]]:
    """Generate mermaid lines for things (commodities/facilities).

    Args:
        things: List of thing dictionaries

    Returns:
        Tuple of (lines, id_to_label_map)
    """
    lines = ["    %% Commodities & Facilities"]
    id_to_label: Dict[str, str] = {}
    for thing in things:
        label = thing["name"]
        node_id = thing["id"]
        id_to_label[node_id] = label
        lines.append(f"    {node_id}[{label}]")
    return lines, id_to_label


def _generate_mermaid_processes(
    processes: List[Dict[str, Any]]
) -> Tuple[List[str], List[Tuple[str, Dict[str, Any]]]]:
    """Generate mermaid lines for processes.

    Args:
        processes: List of process dictionaries

    Returns:
        Tuple of (lines, process_ids_with_data)
    """
    lines = ["\n    %% Recipes"]
    process_ids: List[Tuple[str, Dict[str, Any]]] = []
    for i, process in enumerate(processes, start=1):
        pid = f"R{i}"
        process_ids.append((pid, process))
        lines.append(f"    {pid}[[{process['name']}]]")
    return lines, process_ids


def _generate_mermaid_edges(
    process_ids: List[Tuple[str, Dict[str, Any]]], id_to_label: Dict[str, str]
) -> List[str]:
    """Generate mermaid edge lines.

    Args:
        process_ids: List of (process_id, process_data) tuples
        id_to_label: Map of IDs to labels

    Returns:
        List of edge definition lines
    """
    lines = ["\n    %% Graph Edges: Inputs and Outputs"]
    for pid, process in process_ids:
        for output in process.get("outputs", {}):
            lines.append(f"    {pid} --> {output}")
        for input_ in process.get("inputs", {}):
            lines.append(f"    {input_} --> {pid}")
        for tool in process.get("tools_required", {}):
            lines.append(f"    {tool} --> {pid}")
        for fac in process.get("facilities_required", []):
            lines.append(f"    {fac} --> {pid}")
    return lines


def _generate_mermaid(things_yaml: Path, processes_yaml: Path) -> str:
    """Generate Mermaid diagram code.

    Args:
        things_yaml: Path to commodities YAML
        processes_yaml: Path to processes YAML

    Returns:
        Mermaid diagram code
    """
    things = _load_yaml(things_yaml)
    processes = _load_yaml(processes_yaml)

    lines = ["flowchart BT"]
    thing_lines, id_to_label = _generate_mermaid_things(things)
    lines.extend(thing_lines)

    proc_lines, process_ids = _generate_mermaid_processes(processes)
    lines.extend(proc_lines)

    edge_lines = _generate_mermaid_edges(process_ids, id_to_label)
    lines.extend(edge_lines)

    return "\n".join(lines)


def _render_mermaid_to_file(mermaid_code: str, output_path: Path, format: str) -> bool:
    """Render mermaid code to file.

    Args:
        mermaid_code: Mermaid diagram code
        output_path: Output file path
        format: Output format (svg, png, pdf)

    Returns:
        True if successful, False otherwise
    """
    tmpdir = tempfile.TemporaryDirectory()
    mmd_file = Path(tmpdir.name) / "diagram.mmd"
    mmd_file.write_text(mermaid_code)

    try:
        subprocess.run(
            ["mmdc", "-i", str(mmd_file), "-o", str(output_path), "-f", format],
            check=True,
        )
        print_success(f"Diagram saved to {output_path}")
        return True
    except FileNotFoundError:
        print_error(
            "mmdc not found. Install with: npm install -g @mermaid-js/mermaid-cli"
        )
        return False
    except subprocess.CalledProcessError as e:
        print_error(f"Rendering failed: {e}")
        return False


def _render_mermaid_to_temp(
    mermaid_code: str, format: str, open_after: bool
) -> bool:
    """Render mermaid code to temporary file.

    Args:
        mermaid_code: Mermaid diagram code
        format: Output format (svg, png, pdf)
        open_after: Whether to open after rendering

    Returns:
        True if successful, False otherwise
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        mmd_file = tmpdir_path / "diagram.mmd"
        out_file = tmpdir_path / f"diagram.{format}"

        mmd_file.write_text(mermaid_code)

        try:
            subprocess.run(
                ["mmdc", "-i", str(mmd_file), "-o", str(out_file), "-f", format],
                check=True,
            )
            print_success(f"Rendered to {out_file}")
        except FileNotFoundError:
            print_error(
                "mmdc not found. Install with: npm install -g @mermaid-js/mermaid-cli"
            )
            return False
        except subprocess.CalledProcessError as e:
            print_error(f"Rendering failed: {e}")
            return False

        if open_after:
            _open_rendered_file(out_file)
            input("\n[Press Enter to clean up and exit]")

        return True


def _open_rendered_file(path: Path) -> None:
    """Open rendered file in editor.

    Args:
        path: Path to file
    """
    try:
        subprocess.run(["code", str(path)], check=False)
    except Exception:
        print("Unable to open file automatically.")


def execute(args: argparse.Namespace) -> int:
    """Execute the graph command.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    # Generate mermaid code
    commodities_yaml = Path("data/commodities.yaml")
    processes_yaml = Path("data/processes.yaml")

    if not commodities_yaml.exists():
        print_error(f"Commodities file not found: {commodities_yaml}")
        return 1

    if not processes_yaml.exists():
        print_error(f"Processes file not found: {processes_yaml}")
        return 1

    mermaid_code = _generate_mermaid(commodities_yaml, processes_yaml)

    # Render diagram
    if args.out:
        output_path = Path(f"{args.out}.{args.format}")
        success = _render_mermaid_to_file(mermaid_code, output_path, args.format)
        if success and args.open:
            _open_rendered_file(output_path)
        return 0 if success else 1
    else:
        success = _render_mermaid_to_temp(
            mermaid_code, format=args.format, open_after=args.open
        )
        return 0 if success else 1
