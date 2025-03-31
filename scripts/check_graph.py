import yaml
import subprocess
from pathlib import Path
import tempfile
import shutil
import os

def load_yaml(file_path):
    with open(file_path, 'r') as f:
        return yaml.safe_load(f)

def generate_mermaid_things(things):
    lines = ["    %% Commodities & Facilities"]
    id_to_label = {}
    for thing in things:
        label = thing["name"]
        node_id = thing["id"]
        id_to_label[node_id] = label
        lines.append(f"    {node_id}[{label}]")
    return lines, id_to_label

def generate_mermaid_processes(processes):
    lines = ["\n    %% Recipes"]
    process_ids = []
    for i, process in enumerate(processes, start=1):
        pid = f"R{i}"
        process_ids.append((pid, process))
        lines.append(f"    {pid}[[{process['name']}]]")
    return lines, process_ids

def generate_mermaid_edges(process_ids, id_to_label):
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

def generate_mermaid(things_yaml, processes_yaml):
    things = load_yaml(things_yaml)
    processes = load_yaml(processes_yaml)

    lines = ["flowchart BT"]
    thing_lines, id_to_label = generate_mermaid_things(things)
    lines.extend(thing_lines)

    proc_lines, process_ids = generate_mermaid_processes(processes)
    lines.extend(proc_lines)

    edge_lines = generate_mermaid_edges(process_ids, id_to_label)
    lines.extend(edge_lines)

    return "\n".join(lines)

def render_mermaid_to_temp(mermaid_code, format="svg", open_after=False):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        mmd_file = tmpdir_path / "diagram.mmd"
        out_file = tmpdir_path / f"diagram.{format}"

        mmd_file.write_text(mermaid_code)

        try:
            subprocess.run([
                "mmdc",
                "-i", str(mmd_file),
                "-o", str(out_file),
                "-f", format
            ], check=True)
            print(f"[✓] Rendered to {out_file}")
        except FileNotFoundError:
            print("Error: `mmdc` not found. Please install it with: npm install -g @mermaid-js/mermaid-cli")
            return
        except subprocess.CalledProcessError as e:
            print(f"Rendering failed: {e}")
            return

        if open_after:
            open_rendered_file(out_file)

        # Pause so temp dir isn't deleted instantly (only when opening inline)
        if open_after:
            input("\n[Press Enter to clean up and exit]")

def render_mermaid_to_file(mermaid_code, output_path, format="svg"):
    tmpdir = tempfile.TemporaryDirectory()
    mmd_file = Path(tmpdir.name) / "diagram.mmd"
    mmd_file.write_text(mermaid_code)

    try:
        subprocess.run([
            "mmdc",
            "-i", str(mmd_file),
            "-o", str(output_path),
            "-f", format
        ], check=True)
        print(f"[✓] Rendered diagram saved to {output_path}")
    except Exception as e:
        print(f"Rendering failed: {e}")

def open_rendered_file(path):
    try:
        subprocess.run(["code", str(path)], check=False)
    except Exception:
        print("Unable to open file automatically.")

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Convert YAML to Mermaid and render to image.")
    parser.add_argument("--out", "-o", help="Save output to this base filename (no extension)")
    parser.add_argument("--format", "-f", help="Output format (png, svg, pdf)", default="svg")
    parser.add_argument("--open", action="store_true", help="Open the output diagram after rendering")

    args = parser.parse_args()

    mermaid_code = generate_mermaid("data/commodities.yaml", "data/processes.yaml")

    if args.out:
        output_path = Path(f"{args.out}.{args.format}")
        render_mermaid_to_file(mermaid_code, output_path, args.format)
        if args.open:
            open_rendered_file(output_path)
    else:
        render_mermaid_to_temp(mermaid_code, format=args.format, open_after=args.open)
