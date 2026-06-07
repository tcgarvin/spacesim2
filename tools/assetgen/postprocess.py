"""Post-processing for raw provider output -> committed game sprites.

Nano Banana returns a painterly planet rendered on a (roughly) black void. The
runtime wants a transparent, square, centered planet disc it can blit and tint.
This module finds the lit disc, builds a feathered circular alpha mask, recenters
it on a square canvas, and resizes to the target sprite size.

Pure Pillow + numpy; no network, no provider knowledge. Safe to unit-test on a
fixture PNG.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

# Pixels dimmer than this (0-255 luminance) are treated as background void.
_DISC_LUMA_THRESHOLD = 28
# Alpha ramps from 1 -> 0 between these fractions of the detected disc radius.
_ALPHA_INNER = 0.99
_ALPHA_OUTER = 1.06


def _luma(rgb: np.ndarray) -> np.ndarray:
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def disc_alpha_crop(img: Image.Image, size: int = 256) -> Image.Image:
    """Detect the planet disc on a dark background and return an RGBA sprite.

    The disc is located by thresholding luminance; its centroid and radius set a
    feathered circular alpha mask. The result is recentered on a transparent
    square canvas and resized to ``size`` x ``size``.
    """
    rgb = np.asarray(img.convert("RGB"), dtype=np.float64)
    h, w = rgb.shape[:2]
    lit = _luma(rgb) > _DISC_LUMA_THRESHOLD
    if not lit.any():
        raise ValueError("no lit disc found; image looks fully dark")

    ys, xs = np.nonzero(lit)
    cy = (ys.min() + ys.max()) / 2.0
    cx = (xs.min() + xs.max()) / 2.0
    # Radius from the tighter of the two extents so a non-square frame doesn't
    # stretch the disc; the lit region of a planet is near-circular anyway.
    radius = min(ys.max() - ys.min(), xs.max() - xs.min()) / 2.0
    radius = max(radius, 1.0)

    yy, xx = np.mgrid[0:h, 0:w]
    dist = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2) / radius
    alpha = np.clip((_ALPHA_OUTER - dist) / (_ALPHA_OUTER - _ALPHA_INNER), 0.0, 1.0)

    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[..., :3] = rgb.astype(np.uint8)
    rgba[..., 3] = (alpha * 255).astype(np.uint8)
    out = Image.fromarray(rgba, mode="RGBA")

    # Crop to a square around the disc, with a little margin for the feather.
    side = int(radius * 2 * _ALPHA_OUTER) + 2
    left = int(round(cx - side / 2))
    top = int(round(cy - side / 2))
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(out.crop((left, top, left + side, top + side)), (0, 0))
    return square.resize((size, size), Image.Resampling.LANCZOS)


def process_file(src: Path, dst: Path, size: int = 256) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    sprite = disc_alpha_crop(Image.open(src), size=size)
    sprite.save(dst)
    return dst


if __name__ == "__main__":
    import sys

    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    size = int(sys.argv[3]) if len(sys.argv) > 3 else 256
    print("wrote", process_file(src, dst, size))
