"""Working out a value range ("between 10 and 20 m/s") from the per-frame histograms.

Each frame has hist[hemisphere, longitude strip, bin] = share of the globe whose value
falls in that bin (see field.py). A range covers some bins fully and the two edge bins
partly, so weights() gives each bin the share of it that lies inside the range.
"""

import numpy as np


def weights(edges, low, high, log=False):
    """Share of each bin inside [low, high] (None = no limit on that side)."""
    e = np.asarray(edges, float)
    lo = -np.inf if low is None else float(low)
    hi = np.inf if high is None else float(high)
    if log and e[0] > 0:
        f = np.log
        lo = -np.inf if lo <= 0 else f(lo)
        hi = f(hi) if np.isfinite(hi) and hi > 0 else hi
        e = f(e)
    a, b = e[:-1], e[1:]
    return np.clip((np.minimum(b, hi) - np.maximum(a, lo)) / (b - a), 0, 1)


def centers(edges, log=False):
    e = np.asarray(edges, float)
    return np.sqrt(e[:-1] * e[1:]) if log and e[0] > 0 else (e[:-1] + e[1:]) / 2


class Range:
    """Precomputed helpers for one range on one track."""

    def __init__(self, edges, low, high, log=False):
        self.w = weights(edges, low, high, log)
        self.c = centers(edges, log)

    def area(self, hist, hemisphere="all"):
        """Share of the globe (or of one hemisphere) inside the range. hist: (frames, 2, strips, bins)."""
        h = hist if hemisphere == "all" else hist[:, :1] if hemisphere == "north" else hist[:, 1:]
        inside = (h * self.w).sum(axis=(1, 2, 3))
        total = h.sum(axis=(1, 2, 3))
        return inside / np.maximum(total, 1e-12)

    def per_strip(self, hist):
        """Per longitude strip: share of the strip inside the range, and the average value there."""
        h = hist.sum(axis=1)                                   # both hemispheres: (frames, strips, bins)
        inside = (h * self.w).sum(axis=2)
        share = inside / np.maximum(h.sum(axis=2), 1e-12)
        mean = (h * self.w * self.c).sum(axis=2) / np.maximum(inside, 1e-12)
        return share, mean
