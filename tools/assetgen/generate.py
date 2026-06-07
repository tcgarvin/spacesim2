"""Generate raw provider art for manifest entries and post-process to candidates.

    uv run python tools/assetgen/generate.py                 # all entries
    uv run python tools/assetgen/generate.py --id terran     # one entry
    uv run python tools/assetgen/generate.py --category planet

Writes raw output to staging/raw/<id>.png and the cleaned sprite to
staging/candidates/<id>.png. Review candidates, flip ``status: approved`` in the
manifest, then run promote.py.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml
from postprocess import process_file

_HERE = Path(__file__).resolve().parent


def _load_manifest() -> dict:
    manifest: dict = yaml.safe_load((_HERE / "manifest.yaml").read_text())
    return manifest


def _full_prompt(manifest: dict, entry: dict) -> str:
    prompt = str(entry["prompt"]).strip()
    if entry["category"] == "planet":
        return f"{prompt} {str(manifest['planet_style']).strip()}"
    return prompt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", help="generate only this asset id")
    parser.add_argument("--category", help="generate only this category")
    args = parser.parse_args()

    manifest = _load_manifest()
    entries = manifest["assets"]
    if args.id:
        entries = [e for e in entries if e["id"] == args.id]
    if args.category:
        entries = [e for e in entries if e["category"] == args.category]
    if not entries:
        raise SystemExit("no matching manifest entries")

    for entry in entries:
        provider = entry["provider"]
        if provider != "nanobanana":
            print(f"skip {entry['id']}: provider '{provider}' not wired here yet")
            continue
        from nanobanana import generate_image

        raw = _HERE / "staging" / "raw" / f"{entry['id']}.png"
        candidate = _HERE / "staging" / "candidates" / f"{entry['id']}.png"
        print(f"generating {entry['id']} ...")
        generate_image(_full_prompt(manifest, entry), raw)
        process_file(raw, candidate, size=int(entry.get("size", 256)))
        print(f"  -> {candidate}")


if __name__ == "__main__":
    main()
