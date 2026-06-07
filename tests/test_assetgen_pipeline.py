"""Tests for the offline asset pipeline's post-processing (no network/keys).

Only the pure image transform is exercised here; provider clients are dev-only
and require API keys, so they are not imported in CI.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

_POSTPROCESS = (
    Path(__file__).resolve().parents[1] / "tools" / "assetgen" / "postprocess.py"
)


def _load_postprocess():
    spec = importlib.util.spec_from_file_location("assetgen_postprocess", _POSTPROCESS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _planet_on_black(size: int = 200, radius: int = 70) -> Image.Image:
    """A bright disc centered on a black frame, like raw provider output."""
    yy, xx = np.mgrid[0:size, 0:size]
    inside = (yy - size / 2) ** 2 + (xx - size / 2) ** 2 <= radius**2
    rgb = np.zeros((size, size, 3), dtype=np.uint8)
    rgb[inside] = (120, 160, 220)
    return Image.fromarray(rgb, mode="RGB")


def test_disc_alpha_crop_makes_corners_transparent_and_center_opaque() -> None:
    module = _load_postprocess()
    sprite = module.disc_alpha_crop(_planet_on_black(), size=128)

    assert sprite.size == (128, 128)
    assert sprite.mode == "RGBA"
    alpha = np.asarray(sprite)[..., 3]
    # Corners are background void -> fully transparent.
    assert alpha[0, 0] == 0
    assert alpha[-1, -1] == 0
    # The disc center is fully opaque.
    assert alpha[64, 64] == 255


def test_disc_alpha_crop_rejects_fully_dark_image() -> None:
    module = _load_postprocess()
    black = Image.new("RGB", (64, 64), (0, 0, 0))
    with pytest.raises(ValueError):
        module.disc_alpha_crop(black)
