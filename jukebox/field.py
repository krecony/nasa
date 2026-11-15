"""Analysis for "field" videos: a value everywhere on the map (e.g. temperature).

Unlike rain (which appears and disappears), a field covers the whole map with a
continuous color scale. We turn every pixel into a number with the official
color bar (tracks/<name>/colorbar.png, read by colorbar.py), then measure:

  mean          global average (area-weighted), e.g. degrees C
  lat_mean      average in 5 latitude bands: 60-90N, 30-60N, 30S-30N, 30-60S, 60-90S
  hot_area      share of the globe above `hot_threshold`
  band_hot      share of each 30-degree longitude strip above `hot_threshold` (W -> E)
  band_hot_val  average value of the hot part of each strip
  hot_lon_c     where the hot area is centred (longitude)
  freeze_nh     share of the Northern Hemisphere below `cold_threshold` (0 C)
  freeze_area   same for the whole globe
  cold_area     share of the globe below `very_cold_threshold`
  hottest / coldest   the warmest 10x10 degree square, and the coldest one outside Antarctica
  hist          how much of the globe has each value, per hemisphere (N/S) and per 30-degree
                longitude strip: shape (2, 12, N_BINS), fractions of the globe. The sounds use it
                to work out any value range afterwards ("where is it between 10 and 20 m/s?")
                without reading the video again.
"""

import cv2
import numpy as np

from .colorbar import read_colorbar
from .regions import place_name
from .video import read_frames, video_info

WORK_W, WORK_H = 1024, 512
N_BANDS = 12
N_BINS = 80
LAT_EDGES = [90, 60, 30, -30, -60, -90]
LAT_NAMES = ["Arctic (60-90N)", "northern mid-latitudes", "tropics", "southern mid-latitudes", "Antarctic (60-90S)"]
LUT_BITS = 6


def to_lab(rgb):
    """RGB 0..255 -> CIELAB, where distances match how different colors look
    (e.g. dark navy vs dark brown are close in RGB but clearly different in Lab)."""
    a = np.asarray(rgb, np.float32).reshape(-1, 1, 3) / 255.0
    return cv2.cvtColor(a, cv2.COLOR_RGB2LAB).reshape(-1, 3)


def build_lut(colors, values, max_distance, space="rgb"):
    """Every rounded RGB color -> (value, matched?).

    space = "rgb": plain color distance (0..441); "lab": perceptual distance (0..~100)."""
    levels = (np.arange(1 << LUT_BITS) + 0.5) * (256 / (1 << LUT_BITS))
    r, g, b = np.meshgrid(levels, levels, levels, indexing="ij")
    grid = np.stack([r, g, b], -1).reshape(-1, 3)
    if space == "lab":
        grid, colors = to_lab(grid), to_lab(colors)
    val = np.empty(len(grid))
    ok = np.empty(len(grid), bool)
    for s in range(0, len(grid), 16384):                  # in chunks to save memory
        d = np.linalg.norm(grid[s:s + 16384, None, :] - colors[None], axis=-1)
        val[s:s + 16384] = values[d.argmin(1)]
        ok[s:s + 16384] = d.min(1) <= max_distance
    return val.astype(np.float32), ok


class FieldExtractor:
    def __init__(self, preset, video_path, root):
        self.preset = preset
        self.info = video_info(video_path)
        colors, values = read_colorbar(preset["colorbar"], root)
        # value bins for the histograms (log-spaced for a log color bar)
        lo, hi = float(values.min()), float(values.max())
        um = preset.get("unmatched_value")
        if um is not None:
            lo, hi = min(lo, float(um)), max(hi, float(um))
        if (preset["colorbar"].get("scale") == "log") and lo > 0:
            self.edges = np.geomspace(lo, hi * 1.0001, N_BINS + 1)
        else:
            self.edges = np.linspace(lo, hi + (hi - lo) * 1e-4, N_BINS + 1)
        self.lut_val, self.lut_ok = build_lut(colors, values, preset["max_color_distance"],
                                              preset.get("color_space") or "rgb")

        sx, sy = WORK_W / self.info["width"], WORK_H / self.info["height"]
        self.valid = np.ones((WORK_H, WORK_W), bool)
        for x0, y0, x1, y1 in preset["ignore"]:
            self.valid[int(y0 * sy):int(y1 * sy), int(x0 * sx):int(x1 * sx)] = False

        m = preset["map"]
        self.lat = m["lat_max"] - (np.arange(WORK_H) + 0.5) / WORK_H * (m["lat_max"] - m["lat_min"])
        self.lon = m["lon_min"] + (np.arange(WORK_W) + 0.5) / WORK_W * (m["lon_max"] - m["lon_min"])
        self.coslat = np.cos(np.radians(self.lat))[:, None]
        self.band_of_col = np.minimum((np.arange(WORK_W) * N_BANDS) // WORK_W, N_BANDS - 1)
        self.lat_band = np.digitize(-self.lat, [-e for e in LAT_EDGES[1:-1]])   # 0 = Arctic ... 4 = Antarctic
        self.nh = (self.lat > 0)[:, None]
        # hemisphere (0 = north, 1 = south) and longitude strip of every pixel, for the histograms
        self.cell_index = ((self.lat <= 0)[:, None] * N_BANDS + self.band_of_col[None, :]) * N_BINS

        # 10x10 degree cells
        self.cr = np.minimum((np.arange(WORK_H) * 18) // WORK_H, 17)
        self.cc = np.minimum((np.arange(WORK_W) * 36) // WORK_W, 35)
        self.rs = np.searchsorted(self.cr, np.arange(18))
        self.cs = np.searchsorted(self.cc, np.arange(36))

        # running stats of a coarse grid, for the land mask (land swings more day/night)
        self.s1 = np.zeros((WORK_H // 4, WORK_W // 4))
        self.s2 = np.zeros_like(self.s1)
        self.cnt = np.zeros_like(self.s1)
        self.prev_small = None

    def to_values(self, frame):
        small = cv2.resize(frame, (WORK_W, WORK_H), interpolation=cv2.INTER_NEAREST)
        q = (small >> (8 - LUT_BITS)).astype(np.int32)
        key = (q[..., 0] << (2 * LUT_BITS)) | (q[..., 1] << LUT_BITS) | q[..., 2]
        val = self.lut_val[key]
        ok = self.lut_ok[key]
        unmatched = self.preset.get("unmatched_value")
        if unmatched is not None:
            # colors that aren't on the bar are the bare map showing through: they get this value
            val = np.where(ok, val, np.float32(unmatched))
            ok = np.ones_like(ok)
        return small, val, ok & self.valid

    def _cells(self, a):
        return np.add.reduceat(np.add.reduceat(a, self.rs, axis=0), self.cs, axis=1)

    def frame_features(self, frame):
        p = self.preset
        small, T, ok = self.to_values(frame)
        w = self.coslat * ok
        tot = w.sum()
        Tz = np.where(ok, T, 0.0)
        out = {"mean": float((w * Tz).sum() / tot)}

        b = np.clip(np.searchsorted(self.edges, T, side="right") - 1, 0, N_BINS - 1)
        hist = np.bincount((self.cell_index + b).ravel(), weights=w.ravel(), minlength=2 * N_BANDS * N_BINS)
        out["hist"] = (hist / tot).reshape(2, N_BANDS, N_BINS).astype(np.float32)
        out["hist_edges"] = self.edges

        lat_w = np.bincount(self.lat_band, w.sum(1), 5)
        lat_wt = np.bincount(self.lat_band, (w * Tz).sum(1), 5)
        out["lat_mean"] = lat_wt / np.maximum(lat_w, 1e-9)

        hot = (T >= p["hot_threshold"]) & ok
        wh = w * hot
        col_hot = wh.sum(0)
        band_tot = np.bincount(self.band_of_col, w.sum(0), N_BANDS)
        band_hot = np.bincount(self.band_of_col, col_hot, N_BANDS)
        out["band_hot"] = band_hot / np.maximum(band_tot, 1e-9)
        out["band_hot_val"] = np.bincount(self.band_of_col, (wh * Tz).sum(0), N_BANDS) / np.maximum(band_hot, 1e-9)
        out["hot_area"] = float(wh.sum() / tot)
        if col_hot.sum() > 0:
            lr = np.radians(self.lon)
            out["hot_lon_c"] = float(np.degrees(np.arctan2((col_hot * np.sin(lr)).sum(), (col_hot * np.cos(lr)).sum())))
        else:
            out["hot_lon_c"] = 0.0

        freeze = (T < p["cold_threshold"]) & ok
        out["freeze_area"] = float((w * freeze).sum() / tot)
        out["freeze_nh"] = float((w * freeze * self.nh).sum() / max((w * self.nh).sum(), 1e-9))
        out["cold_area"] = float((w * ((T < p["very_cold_threshold"]) & ok)).sum() / tot)

        cw = self._cells(w)
        cells = self._cells(w * Tz) / np.maximum(cw, 1e-9)
        cells[cw < 0.25 * cw.max(axis=1, keepdims=True)] = np.nan    # squares mostly hidden (logo, timestamp)
        r, c = np.unravel_index(np.nanargmax(cells), cells.shape)
        out["hottest"] = (float(cells[r, c]), 85 - 10 * r, -175 + 10 * c)
        masked = cells.copy()
        masked[15:] = np.nan                              # rows for 60-90S = Antarctica
        r, c = np.unravel_index(np.nanargmin(masked), masked.shape)
        out["coldest"] = (float(cells[r, c]), 85 - 10 * r, -175 + 10 * c)

        # for the land mask
        coarse = T[::4, ::4]
        okc = ok[::4, ::4]
        self.s1 += np.where(okc, coarse, 0)
        self.s2 += np.where(okc, coarse ** 2, 0)
        self.cnt += okc

        g = cv2.resize(small, (256, 128), interpolation=cv2.INTER_AREA).astype(np.int16)
        out["hold"] = self.prev_small is not None and np.abs(g - self.prev_small).mean() < 0.3
        out["change"] = 0.0 if self.prev_small is None else float(np.abs(g - self.prev_small).mean())
        self.prev_small = g
        return out

    def land_mask(self, min_std=2.5):
        """Land swings between day and night much more than the ocean does."""
        n = np.maximum(self.cnt, 1)
        std = np.sqrt(np.maximum(self.s2 / n - (self.s1 / n) ** 2, 0))
        return std >= min_std


def extract_field(preset, video_path, root, progress=True):
    fx = FieldExtractor(preset, video_path, root)
    feats = []
    for i, frame in read_frames(video_path):
        feats.append(fx.frame_features(frame))
        if progress and i % 50 == 0:
            print(f"  frame {i}/{fx.info['frames']}", flush=True)

    # name the hottest / coldest places, now that we know where land is
    land = fx.land_mask()
    lh, lw = land.shape

    def is_land(lat, lon):
        r0 = int((90 - (lat + 5)) / 180 * lh); r1 = int((90 - (lat - 5)) / 180 * lh)
        c0 = int((lon - 5 + 180) / 360 * lw); c1 = int((lon + 5 + 180) / 360 * lw)
        return land[r0:r1, c0:c1].mean() > 0.5

    names = {}
    for f in feats:
        for k in ("hottest", "coldest"):
            _, lat, lon = f[k]
            if (lat, lon) not in names:
                names[(lat, lon)] = place_name(lat, lon, is_land(lat, lon))
            f[k + "_place"] = names[(lat, lon)]
    fx.layers = ["temperature"]
    return fx, feats
