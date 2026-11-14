"""Turning colors back into numbers using the visualization's own color bar.

Idea: the legend tells us "this green = 0.5-1.0 mm/hour". We read those
legend colors from the first frame, then for every pixel ask "which legend
color is this closest to?".

Two things make this harder than exact color matching:
  1. The rain is drawn semi-transparent, so edges are darker than the legend.
  2. Video compression smears colors (it stores color at lower resolution).
Both mostly change brightness and saturation, but keep the HUE. So we match on
hue (plus a little on brightness to tell red from dark red).

To stop land (deserts, forests) from being read as rain, features.py also
compares every frame with the static background map (see background()).

For speed we build a lookup table (LUT) once: all 32x32x32 "rounded" RGB
colors -> which legend entry they match (or -1). Each frame is then
classified with a single array lookup.
"""

import numpy as np

LUT_BITS = 5                 # 5 bits per channel -> 32 levels
LUT_LEVELS = 1 << LUT_BITS


def rgb_to_hsv(rgb):
    """rgb: (..., 3) floats 0..255 -> hue in degrees 0..360, sat 0..1, val 0..1"""
    rgb = np.asarray(rgb, dtype=float) / 255.0
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx, mn = rgb.max(-1), rgb.min(-1)
    delta = mx - mn
    safe = np.where(delta == 0, 1, delta)
    h = np.where(mx == r, ((g - b) / safe) % 6,
        np.where(mx == g, (b - r) / safe + 2, (r - g) / safe + 4)) * 60.0
    h = np.where(delta == 0, 0, h)
    s = np.where(mx == 0, 0, delta / np.where(mx == 0, 1, mx))
    return h, s, mx


def sample_legend(frame, layer, half=6, rows=4):
    """Read the color in the middle of each bin of one color bar.

    Returns (colors, values): colors is (n_bins, 3) RGB, values is (n_bins,)
    """
    edges = np.array(layer["edges"], dtype=float)
    n_bins = len(edges) - 1
    w, x0, y = layer["bin_width"], layer["bar_x0"], layer["bar_y"]
    colors = []
    for i in range(n_bins):
        cx = x0 + w * i + w // 2
        patch = frame[y - rows:y + rows + 1, cx - half:cx + half + 1].reshape(-1, 3)
        colors.append(np.median(patch, axis=0))
    values = np.sqrt(edges[:-1] * edges[1:])   # geometric middle of each bin
    return np.array(colors), values


def build_lut(legend_colors, min_sat=0.45, min_val=0.35, max_hue_dist=25, val_weight=25):
    """Map every rounded RGB color to an index into legend_colors, or -1."""
    levels = (np.arange(LUT_LEVELS) + 0.5) * (256 / LUT_LEVELS)
    r, g, b = np.meshgrid(levels, levels, levels, indexing="ij")
    grid = np.stack([r, g, b], axis=-1).reshape(-1, 3)              # (32768, 3)

    h, s, v = rgb_to_hsv(grid)
    lh, _, lv = rgb_to_hsv(legend_colors)

    hue_dist = np.abs(h[:, None] - lh[None, :])
    hue_dist = np.minimum(hue_dist, 360 - hue_dist)                 # hue wraps around
    score = hue_dist + val_weight * np.abs(v[:, None] - lv[None, :])
    nearest = score.argmin(axis=1)

    ok = (s >= min_sat) & (v >= min_val) & (hue_dist.min(axis=1) <= max_hue_dist)
    nearest[~ok] = -1
    return nearest.astype(np.int16)


class Palette:
    """All color bars of a preset combined into one classifier."""

    def __init__(self, frame, preset):
        self.layer_names = list(preset["layers"])
        colors, values, layer_idx = [], [], []
        for li, name in enumerate(self.layer_names):
            c, v = sample_legend(frame, preset["layers"][name])
            colors.append(c)
            values.append(v)
            layer_idx += [li] * len(v)
        self.colors = np.vstack(colors)
        self.values = np.concatenate(values)             # mm/hour per legend entry
        self.layer_of = np.array(layer_idx)               # which layer per entry
        self.lut = build_lut(self.colors, **preset.get("color_match", {}))

    def classify(self, frame):
        """Return (layer_index, value) arrays with the frame's height/width.

        layer_index is -1 where the pixel is not data; value is 0 there.
        """
        q = (frame >> (8 - LUT_BITS)).astype(np.int32)
        key = (q[..., 0] << (2 * LUT_BITS)) | (q[..., 1] << LUT_BITS) | q[..., 2]
        entry = self.lut[key]
        is_data = entry >= 0
        layer = np.where(is_data, self.layer_of[entry], -1)
        value = np.where(is_data, self.values[entry], 0.0)
        return layer, value


def background(frames):
    """The static map under the data: per-pixel median over many frames.

    Rain covers any one spot only a small part of the time, so the median
    is the bare map (land, ocean, ice).
    """
    return np.median(np.stack(frames), axis=0).astype(np.uint8)
