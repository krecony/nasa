"""Analysis for "field" videos: a value everywhere on the map (e.g. temperature).

Unlike rain (which appears and disappears), a field covers the whole map with a
continuous color scale. We turn every pixel into a number with the official
color bar (an image in colorbars/, read by colorbar.py), then measure:

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
"""

import cv2
import numpy as np

from .colorbar import read_colorbar
from .regions import place_name
from .video import read_frames, video_info

WORK_W, WORK_H = 1024, 512
N_BANDS = 12
LAT_EDGES = [90, 60, 30, -30, -60, -90]
LAT_NAMES = ["Arctic (60-90N)", "northern mid-latitudes", "tropics", "southern mid-latitudes", "Antarctic (60-90S)"]
LUT_BITS = 6


def build_lut(colors, values, max_distance):
    """Every rounded RGB color -> (value, matched?)."""
    levels = (np.arange(1 << LUT_BITS) + 0.5) * (256 / (1 << LUT_BITS))
    r, g, b = np.meshgrid(levels, levels, levels, indexing="ij")
    grid = np.stack([r, g, b], -1).reshape(-1, 3)
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
        self.lut_val, self.lut_ok = build_lut(colors, values, preset["max_color_distance"])

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
        ok = self.lut_ok[key] & self.valid
        return small, val, ok

    def _cells(self, a):
        return np.add.reduceat(np.add.reduceat(a, self.rs, axis=0), self.cs, axis=1)

    def frame_features(self, frame):
        p = self.preset
        small, T, ok = self.to_values(frame)
        w = self.coslat * ok
        tot = w.sum()
        Tz = np.where(ok, T, 0.0)
        out = {"mean": float((w * Tz).sum() / tot)}

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

        cells = self._cells(w * Tz) / np.maximum(self._cells(w), 1e-9)
        r, c = np.unravel_index(cells.argmax(), cells.shape)
        out["hottest"] = (float(cells[r, c]), 85 - 10 * r, -175 + 10 * c)
        masked = cells.copy()
        masked[15:] = np.inf                              # rows for 60-90S = Antarctica
        r, c = np.unravel_index(masked.argmin(), masked.shape)
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
