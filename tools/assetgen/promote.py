"""Promote approved candidate sprites into the shipped runtime asset tree.

Copies staging/candidates/<id>.png -> spacesim2/ui/live/assets/<category>/<id>.png
for every manifest entry with ``status: approved``, rewrites the per-category
index.json the runtime loader reads, and records provenance in ATTRIBUTION.md.

    uv run python tools/assetgen/promote.py
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve().parent
_ASSET_ROOT = _HERE.parents[1] / "spacesim2" / "ui" / "live" / "assets"


def main() -> None:
    manifest = yaml.safe_load((_HERE / "manifest.yaml").read_text())
    approved = [e for e in manifest["assets"] if e.get("status") == "approved"]
    if not approved:
        raise SystemExit("no approved assets in manifest")

    by_category: dict[str, list[str]] = {}
    attribution: list[str] = []
    for entry in approved:
        candidate = _HERE / "staging" / "candidates" / f"{entry['id']}.png"
        if not candidate.exists():
            print(f"skip {entry['id']}: no candidate (run generate.py first)")
            continue
        dest_dir = _ASSET_ROOT / f"{entry['category']}s"
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate, dest_dir / f"{entry['id']}.png")
        by_category.setdefault(entry["category"], []).append(entry["id"])
        attribution.append(
            f"- `{entry['category']}/{entry['id']}.png` — {entry['provider']}: "
            f"{entry['prompt'].strip()}"
        )
        print(f"promoted {entry['category']}/{entry['id']}")

    for category, ids in by_category.items():
        index = _ASSET_ROOT / f"{category}s" / "index.json"
        index.write_text(json.dumps({"ids": sorted(ids)}, indent=2) + "\n")

    (_ASSET_ROOT / "ATTRIBUTION.md").write_text(
        "# Asset attribution\n\n"
        "Generated offline by tools/assetgen. Provider + prompt per asset:\n\n"
        + "\n".join(sorted(attribution))
        + "\n"
    )


if __name__ == "__main__":
    main()
