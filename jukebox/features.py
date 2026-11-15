"""Step 1-3 of the pipeline: video frames -> a table of numbers over time.

For every frame we compute, per data layer (e.g. "liquid" rain, "frozen" snow):
  area        fraction of the globe covered (0..1), area-weighted
  rate        global average precipitation rate (mm/hour)
  heavy       fraction of the globe with heavy rates (>= heavy_threshold)
  lon_c/lat_c where the layer is centred (degrees)
  band_area   coverage per longitude band (west -> east), used for stereo
  band_lat    average latitude of the data in each band, used for pitch
  band_rate   average intensity inside each band, used for loudness
plus frame-level values:
  change      how much of the map changed since the previous frame (motion)
  hold        True when the video is just holding a still frame
  hot_lat/lon/place   the 10x10 degree area with the most rain right now

Why "area-weighted"? On a flat world map the poles are stretched: a pixel near
the pole covers far less real area than one at the equator. We weight each
pixel row by cos(latitude) so the numbers mean "fraction of the real globe".
"""

import numpy as np
import cv2

from .palette import Palette, background
from .regions import place_name
from .video import read_frames, first_frame, video_info

WORK_W, WORK_H = 960, 540       # analysis resolution (half of 1080p)
N_BANDS = 12                    # 30-degree longitude bands


def shrink(frame):
    # INTER_NEAREST keeps real legend colors (no blending between pixels)
    return cv2.resize(frame, (WORK_W, WORK_H), interpolation=cv2.INTER_NEAREST)


class FeatureExtractor:
    def __init__(self, preset, video_path, background_every=6):
        self.preset = preset
        self.info = video_info(video_path)
        sx = WORK_W / self.info["width"]
        sy = WORK_H / self.info["height"]

        # Legend colors are read at full resolution from the first frame
        self.palette = Palette(first_frame(video_path), preset)
        self.layers = self.palette.layer_names

        # Static background map (median of every Nth frame)
        frames = [shrink(f) for i, f in read_frames(video_path) if i % background_every == 0]
        self.bg = background(frames).astype(np.int16)
        # Land = bright, or clearly green/brown (ocean here is near-black navy).
        # Then remove small specks (rainy ocean leaves a faint tint in the median).
        r, g, b = self.bg[..., 0], self.bg[..., 1], self.bg[..., 2]
        land = (self.bg.max(-1) >= 60) | ((g - b > 12) & (r >= b))
        kernel = np.ones((5, 5), np.uint8)
        self.is_land = cv2.morphologyEx(land.astype(np.uint8), cv2.MORPH_OPEN, kernel).astype(bool)

        # Mask of areas to ignore (legend, timestamp, logo)
        self.valid = np.ones((WORK_H, WORK_W), bool)
        for x0, y0, x1, y1 in preset["ignore"]:
            self.valid[int(y0 * sy):int(y1 * sy), int(x0 * sx):int(x1 * sx)] = False

        # Latitude / longitude of every pixel row / column
        m = preset["map"]
        self.lat = m["lat_max"] - (np.arange(WORK_H) + 0.5) / WORK_H * (m["lat_max"] - m["lat_min"])
        self.lon = m["lon_min"] + (np.arange(WORK_W) + 0.5) / WORK_W * (m["lon_max"] - m["lon_min"])
        self.w = np.cos(np.radians(self.lat))[:, None] * self.valid   # area weight per pixel
        self.total_w = self.w.sum()
        self.band_of_col = np.minimum((np.arange(WORK_W) * N_BANDS) // WORK_W, N_BANDS - 1)

        # 10x10 degree cells for "where is the heaviest rain"
        self.cell_rows, self.cell_cols = 18, 36
        self.cell_r = np.minimum((np.arange(WORK_H) * self.cell_rows) // WORK_H, self.cell_rows - 1)
        self.cell_c = np.minimum((np.arange(WORK_W) * self.cell_cols) // WORK_W, self.cell_cols - 1)

        self.prev_frame = None
        self.prev_layer = None
        self.prev_cells = None

    def classify(self, small):
        layer, value = self.palette.classify(small)
        diff = np.abs(small.astype(np.int16) - self.bg).max(-1)
        not_data = (diff < self.preset["min_background_diff"]) | ~self.valid
        layer[not_data] = -1
        value[not_data] = 0
        return layer, value

    def _cells(self, arr):
        """Sum an image into 18x36 cells of 10x10 degrees."""
        rows = np.add.reduceat(arr, np.searchsorted(self.cell_r, np.arange(self.cell_rows)), axis=0)
        return np.add.reduceat(rows, np.searchsorted(self.cell_c, np.arange(self.cell_cols)), axis=1)

    def frame_features(self, frame):
        small = shrink(frame)
        layer, value = self.classify(small)
        out = {}

        for li, name in enumerate(self.layers):
            m = (layer == li)
            wm = self.w * m
            area = wm.sum() / self.total_w
            rate = (wm * value).sum() / self.total_w
            heavy = (wm * (value >= self.preset["heavy_threshold"])).sum() / self.total_w

            # per longitude band
            col_w = wm.sum(0)                                   # weight per column
            col_wv = (wm * value).sum(0)
            col_wlat = (wm * self.lat[:, None]).sum(0)
            band_w = np.bincount(self.band_of_col, col_w, N_BANDS)
            band_tot = np.bincount(self.band_of_col, self.w.sum(0), N_BANDS)
            band_area = band_w / np.maximum(band_tot, 1e-9)
            band_rate = np.bincount(self.band_of_col, col_wv, N_BANDS) / np.maximum(band_w, 1e-9)
            band_lat = np.bincount(self.band_of_col, col_wlat, N_BANDS) / np.maximum(band_w, 1e-9)

            # centre: circular mean for longitude (so 179E and 179W average to 180)
            tw = wm.sum()
            if tw > 0:
                lon_r = np.radians(self.lon)
                lon_c = np.degrees(np.arctan2((col_w * np.sin(lon_r)).sum(), (col_w * np.cos(lon_r)).sum()))
                lat_c = (wm.sum(1) * self.lat).sum() / tw
            else:
                lon_c, lat_c = 0.0, 0.0

            out[name] = dict(area=area, rate=rate, heavy=heavy, lon_c=lon_c, lat_c=lat_c,
                             band_area=band_area, band_rate=band_rate, band_lat=band_lat)

        # Where is the most precipitation (all layers) right now?
        cells = self._cells(self.w * value)
        r, c = np.unravel_index(cells.argmax(), cells.shape)
        hot_lat = 90 - (r + 0.5) * 10
        hot_lon = -180 + (c + 0.5) * 10
        land_frac = self._cells(self.w * self.is_land)[r, c] / max(self._cells(self.w)[r, c], 1e-9)
        out["hot_lat"], out["hot_lon"] = hot_lat, hot_lon
        out["hot_place"] = place_name(hot_lat, hot_lon, land_frac > 0.5)

        # Motion: how much the rain pattern moved, measured on 10x10 degree cells
        # (pixel-level comparison is mostly speckle noise from the satellite data)
        if self.prev_layer is None:
            out["change"] = 0.0
        else:
            out["change"] = np.abs(cells - self.prev_cells).sum() / max(cells.sum(), 1e-9)
        self.prev_cells = cells

        # Hold: the video shows the same picture again (e.g. pause at the end)
        out["hold"] = (self.prev_frame is not None and
                       np.abs(small.astype(np.int16) - self.prev_frame).mean() < 0.3)

        self.prev_layer = layer
        self.prev_frame = small.astype(np.int16)
        return out


def extract(preset, video_path, progress=True):
    """Run the extractor over the whole video. Returns (info, list_of_feature_dicts)."""
    fx = FeatureExtractor(preset, video_path)
    feats = []
    for i, frame in read_frames(video_path):
        feats.append(fx.frame_features(frame))
        if progress and i % (50 if progress is True else int(progress)) == 0:
            print(f"  frame {i}/{fx.info['frames']}", flush=True)
    return fx, feats


def smooth(x, frames=5):
    """Moving average so the sound glides instead of jittering."""
    x = np.asarray(x, dtype=float)
    if frames <= 1:
        return x
    k = np.ones(frames) / frames
    pad = frames // 2
    xp = np.pad(x, [(pad, frames - 1 - pad)] + [(0, 0)] * (x.ndim - 1), mode="edge")
    if x.ndim == 1:
        return np.convolve(xp, k, mode="valid")
    return np.stack([np.convolve(xp[:, j], k, mode="valid") for j in range(x.shape[1])], axis=1)


def series(feats, layer, key):
    """Pull one feature out as a time series (array)."""
    return np.array([f[layer][key] for f in feats])
