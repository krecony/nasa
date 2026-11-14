"""Reading a color bar from an image (e.g. the colorbar PNG on the NASA SVS page).

You only say what the ends mean (min and max, e.g. -40 and 40). The bar is found
automatically: it's the biggest long, thin shape that stands out from the
background. Then every pixel along it becomes one entry: color -> value.

If detection ever picks the wrong thing, set "box": [x0, y0, x1, y1] (the inside
of the bar, in image pixels) in the preset's "colorbar" settings.
"""

from pathlib import Path

import cv2
import numpy as np


def find_bar(img):
    """Return (x0, y0, x1, y1) of the bar's inside, in image pixels."""
    h, w = img.shape[:2]
    # background = the most common color (works for plain and see-through backgrounds)
    q = (img // 8).reshape(-1, 3)
    vals, counts = np.unique(q, axis=0, return_counts=True)
    common = np.all(q == vals[counts.argmax()], axis=1)
    bg = np.median(img.reshape(-1, 3)[common], axis=0)
    differs = (np.abs(img.astype(int) - bg).max(-1) > 30).astype(np.uint8)
    best, best_area = None, 0
    # parts of a bar can match the background (e.g. a white section), so bridge
    # gaps along the bar: try horizontal and vertical bars
    for kernel in [(41, 1), (1, 41)]:
        closed = cv2.morphologyEx(differs, cv2.MORPH_CLOSE, np.ones(kernel[::-1], np.uint8))
        n, _, stats, _ = cv2.connectedComponentsWithStats(closed, connectivity=8)
        for k in range(1, n):
            x, y, bw, bh, _ = stats[k]
            long_, short = max(bw, bh), min(bw, bh)
            if long_ >= 4 * short and long_ >= 0.3 * max(w, h) and bw * bh > best_area:
                best, best_area = (x, y, x + bw, y + bh), bw * bh
    if best is None:
        raise SystemExit("Couldn't find a color bar in the image. Crop it closer, or set \"box\" in the preset.")
    x0, y0, x1, y1 = best

    # step inwards past a border line (e.g. a white or black frame around the bar)
    horizontal = (x1 - x0) >= (y1 - y0)
    for _ in range(4):
        if horizontal:
            line = img[(y0 + y1) // 2, x0:x1].astype(int)
            col = img[y0:y1, (x0 + x1) // 2].astype(int)
        else:
            line = img[y0:y1, (x0 + x1) // 2].astype(int)
            col = img[(y0 + y1) // 2, x0:x1].astype(int)
        trimmed = False
        if np.abs(line[0] - line[1]).sum() > 40 or np.abs(line[0] - line[-1]).sum() < 10:
            if horizontal: x0 += 1; x1 -= 1
            else: y0 += 1; y1 -= 1
            trimmed = True
        if np.abs(col[0] - col[len(col) // 2]).sum() > 40:
            if horizontal: y0 += 1; y1 -= 1
            else: x0 += 1; x1 -= 1
            trimmed = True
        if not trimmed:
            break
    return int(x0), int(y0), int(x1), int(y1)


def read_colorbar(spec, root):
    """spec: {"image", "min", "max", optional "scale" ("linear"/"log"), "box", "reverse"}.

    Returns (colors (n,3) RGB floats, values (n,)), low to high.
    Horizontal bars run left (min) -> right (max); vertical bars bottom (min) -> top (max).
    """
    path = Path(spec["image"])
    if not path.is_absolute():
        path = Path(root) / path
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise SystemExit(f"Can't open the color bar image: {path}")
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 4:                       # see-through PNG: put it on mid-grey
        a = img[:, :, 3:4].astype(float) / 255
        img = (img[:, :, :3] * a + 128 * (1 - a)).astype(np.uint8)
    img = img[:, :, ::-1].copy()
    x0, y0, x1, y1 = spec.get("box") or find_bar(img)
    if (x1 - x0) >= (y1 - y0):
        mid, half = (y0 + y1) // 2, max((y1 - y0) // 4, 1)
        colors = np.median(img[mid - half:mid + half + 1, x0:x1], axis=0)
    else:
        mid, half = (x0 + x1) // 2, max((x1 - x0) // 4, 1)
        colors = np.median(img[y0:y1, mid - half:mid + half + 1], axis=1)[::-1]
    if spec.get("reverse"):
        colors = colors[::-1]
    t = (np.arange(len(colors)) + 0.5) / len(colors)
    lo, hi = float(spec["min"]), float(spec["max"])
    if spec.get("scale", "linear") == "log":
        values = lo * (hi / lo) ** t
    else:
        values = lo + t * (hi - lo)
    return colors.astype(float), values
