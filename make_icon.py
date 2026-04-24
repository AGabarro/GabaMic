#!/usr/bin/env python3
"""Generate GabaMic icon assets from the G-logo definition.

Outputs:
    GabaMic.ico  — multi-size Windows icon (16/32/48/64/128/256 px)
    GabaMic.png  — 256 px transparent PNG (macOS menu bar, web favicon)

Run once whenever the logo design changes:
    python make_icon.py
"""
import math
import pathlib
import sys

import numpy as np

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow not installed.  Run: pip install Pillow")

# ── Brand colours (exact values from design system) ──────────────────────────
TEAL   = (0, 255, 239)   # #00FFEF — gradient start (bottom-left)
ORANGE = (255, 98, 0)    # #FF6200 — gradient end   (top-right)

# ── G-logo geometry (in the 200×200 SVG viewBox) ─────────────────────────────
# circle: cx=100 cy=100 r=69 stroke-width=32  →  ring from r=53 to r=85
# stroke-dasharray="361.3 72.3"               →  300° visible, 60° gap at top-right
# rect: x=100 y=84 width=85 height=32         →  horizontal crossbar
CX, CY       = 100.0, 100.0
R_OUTER      = 85.0
R_INNER      = 53.0
GAP_START_DEG = 300.0   # clockwise degrees from 3-o'clock where gap begins

RECT_X1, RECT_Y1 = 100.0, 84.0
RECT_X2, RECT_Y2 = 185.0, 116.0

# ── Gradient ──────────────────────────────────────────────────────────────────
# SVG: x1="15" y1="185" (teal) → x2="185" y2="15" (orange)
# Projection onto gradient vector gives t ∈ [0, 1].
def _gradient_t(ox: np.ndarray, oy: np.ndarray) -> np.ndarray:
    return np.clip((ox - oy + 170.0) / 340.0, 0.0, 1.0)


def _render_raw(size: int) -> Image.Image:
    """Render the G logo at `size`×`size` with a transparent background."""
    scale = 200.0 / size
    axis  = (np.arange(size, dtype=np.float32) + 0.5) * scale
    ox, oy = np.meshgrid(axis, axis)   # shape (size, size)

    # Ring mask
    dx, dy = ox - CX, oy - CY
    dist2  = dx * dx + dy * dy
    in_ring = (dist2 >= R_INNER ** 2) & (dist2 <= R_OUTER ** 2)

    # Remove the gap sector (≥ 300° clockwise from 3-o'clock)
    angle_deg = np.degrees(np.arctan2(dy, dx))
    angle_cw  = np.where(angle_deg < 0, angle_deg + 360.0, angle_deg)
    ring_mask = in_ring & (angle_cw < GAP_START_DEG)

    # Crossbar mask
    rect_mask = (
        (ox >= RECT_X1) & (ox <= RECT_X2) &
        (oy >= RECT_Y1) & (oy <= RECT_Y2)
    )

    g_mask = ring_mask | rect_mask

    # Gradient colours
    t = _gradient_t(ox, oy)
    r = np.round(ORANGE[0] * t + TEAL[0] * (1.0 - t)).astype(np.uint8)
    g = np.round(ORANGE[1] * t + TEAL[1] * (1.0 - t)).astype(np.uint8)
    b = np.round(ORANGE[2] * t + TEAL[2] * (1.0 - t)).astype(np.uint8)
    a = np.where(g_mask, np.uint8(255), np.uint8(0))

    rgba = np.stack([r, g, b, a], axis=-1)
    return Image.fromarray(rgba, "RGBA")


def render(size: int, supersample: int = 4) -> Image.Image:
    """Render with super-sampling for smooth anti-aliased edges."""
    big = _render_raw(size * supersample)
    return big.resize((size, size), Image.LANCZOS)


def main() -> None:
    out = pathlib.Path(__file__).parent

    # ── Windows multi-size .ico ───────────────────────────────────────────────
    # Pillow's ICO plugin derives all sizes from a single source image by
    # downsampling, so we render at 256 px (highest quality) and let it scale.
    ico_sizes = [16, 32, 48, 64, 128, 256]
    ico_src   = render(256)       # single high-res source; Pillow scales down
    ico_path  = out / "GabaMic.ico"
    ico_src.save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in ico_sizes],
    )
    print(f"  GabaMic.ico  — {', '.join(str(s) for s in ico_sizes)} px")

    # ── macOS / web PNG (256 px, transparent) ────────────────────────────────
    png_path = out / "GabaMic.png"
    render(256).save(png_path, format="PNG")
    print(f"  GabaMic.png  — 256 px (transparent)")

    print("Done.")


if __name__ == "__main__":
    main()
