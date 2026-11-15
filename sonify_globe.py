"""Earth Jukebox, globe edition: turn a video of a SPINNING GLOBE into music.

This is a standalone script: it does not import the 2D engine (sonify.py / jukebox/),
so the two can be changed independently. It needs numpy, scipy, opencv-python and
matplotlib (the same as requirements.txt), plus ffmpeg for the video.

Usage:
    py sonify_globe.py ocean_currents videos/CutOceanCurrents.mp4
    py sonify_globe.py temperature_currents videos/CutTemperatureCurrents.mp4
    py sonify_globe.py ocean_currents videos/CutOceanCurrents.mp4 --no-video      skip the video (fast)
    py sonify_globe.py ocean_currents videos/CutOceanCurrents.mp4 --only notes    hear only some layers
    py sonify_globe.py ocean_currents videos/CutOceanCurrents.mp4 --stems         also save each layer
    py sonify_globe.py ocean_currents videos/CutOceanCurrents.mp4 --website       add it to the website

How it works:
    1. MASK      A real map of the world's land (globe_landmask.png, from Natural Earth) is projected
                 onto the globe in every frame, so continents and islands are masked exactly. The
                 script finds which longitude faces the camera by sliding the map until its coasts
                 line up with the picture.
    2. LINE      A line runs down the middle of the globe, from the north edge to the south edge:
                 the meridian that faces the camera. As the globe spins, every ocean passes under it.
                 The line is cut into latitude bins and the colors under it become numbers (0..1).
    3. SPIN      Because the map is lined up with every frame, the script knows how far the globe has
                 turned. The music is clocked by that rotation, not by time: every `degrees_per_step`
                 of spin is one beat. A fast globe plays fast, a slowing globe slows the music down,
                 a stopped globe leaves only the held chord.
    4. MUSIC     On each beat the strongest currents under the line are played as notes:
                 further north = higher, stronger = louder.

Writes (in output/<preset>/):
    sonification.wav      the soundtrack
    stems/*.wav           each layer on its own (with --stems)
    features.png          the globe unrolled under the line, with the notes drawn on it (check this first!)
    features.csv          the numbers per beat
    descriptions.vtt      a sentence per stretch of rotation, for accessibility
    <preset>.mp4          the video with the mask, the line and the soundtrack (needs ffmpeg)
With --website it also copies the mp4 / vtt / png to website/media/ and updates website/tracks.json.

The video analysis is cached (output/<preset>/analysis.npz); after the first run, changing the
sounds only takes a few seconds. Use --reanalyze to force it.
"""

import argparse
import json
import shutil
import subprocess
import sys
import warnings
from pathlib import Path

import cv2
import numpy as np
from scipy import signal
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parent
SR = 44100

# =============================================================================
#  PRESETS: everything specific to one video. Copy one to add a new globe video.
# =============================================================================
#  ramp        the visualization's colors from "nothing" to "strongest", as (R, G, B).
#              Pixels are matched to the nearest point on this ramp and their position
#              along it (0..1) is the value.
#  water_colors  what plain water looks like (dark to light). Only used to line the land map up
#              with the video: a pixel counts as water when its hue matches one of these.
#  globe       how the camera sees the globe. tilt_deg = latitude under the camera,
#              distance = camera distance in globe radii (None = infinitely far),
#              roll_deg = how far the picture is turned clockwise. The globe's centre, its
#              radius and the longitude facing the camera are found automatically.
#  sounds      all the musical choices.

DEFAULT_SOUNDS = {
    "key": "D", "scale": "major_pentatonic",
    "degrees_per_step": 2.0,      # one beat per this much rotation (smaller = busier)
    "max_notes": 3,               # most notes on one beat
    "note_threshold": 0.22,       # a current must be at least this strong (0..1) to be played
    "min_separation_deg": 10,     # notes on the same beat are at least this far apart in latitude
    "hold_steps": 3,              # a current that stays under the line is re-struck every N beats
    "lowest_note": "D3", "highest_note": "D6",   # south end ... north end of the line
    "instrument": "glass",        # glass (soft, slow, ringing), bell, marimba, pluck
    "quiet": 0.3, "loud": 0.9,    # loudness of the weakest / strongest note
    "stereo_width": 0.6,          # north a little to the left, south a little to the right (0 = centre)
    "echo_seconds": 0.42,         # each note repeats more quietly, bouncing between the ears (0 = off)
    "echo_gain": 0.38,
    "chord_every_deg": 90,        # the held chord changes every quarter turn
    "chords": [(0, "maj"), (-3, "min"), (5, "maj"), (7, "maj")],   # semitones from the key, type
    "chord_octave": 3,
    "pad_shimmer": 0.25,          # how much high, slowly breathing overtone the held chord has
    "chime_every_deg": 45,        # a bell marks every eighth of a turn
    "chime_note": "D6",
    "volumes": {"notes": 0.3, "pad": 0.3, "sea": 0.045, "chime": 0.12},
    "reverb_seconds": 6.0, "reverb_wet": 0.5, "peak": 0.89,
    "tail_seconds": 6.0,
}

# Both example videos use the same camera: it looks down on about 9 N from 4.5 globe radii away.
# (Found by trying camera settings until the projected land map matched the video best.)
_CAMERA = {"tilt_deg": 9.0, "distance": 4.5, "roll_deg": 0.0}

PRESETS = {
    "ocean_currents": {
        "id": "ocean_currents",
        "title": "Ocean Currents (spinning globe)",
        "source": "NASA Scientific Visualization Studio (ocean surface currents)",
        "description": (
            "A globe of the Earth turning once. The oceans are drawn in blue, and moving water is drawn "
            "as white streaks: the faster the current, the whiter and denser the streaks. The Gulf Stream, "
            "the Kuroshio off Japan and the currents around Antarctica stand out as bright white rivers. "
            "A line down the middle of the globe reads the currents as each ocean turns past it."
        ),
        "listening_guide": [
            "A line runs from north to south down the middle of the globe. The music is what passes under it.",
            "Each note is a strong current crossing the line. Higher = further north, lower = further south.",
            "Louder notes = stronger, whiter currents.",
            "The beat is the globe's spin: one beat for every 2 degrees it turns. When the globe slows down, so does the music.",
            "The soft wash is open water under the line. It fades when a continent passes.",
            "A bell rings every eighth of a turn, and the held chord changes every quarter turn.",
        ],
        "ramp": [(12, 58, 129), (45, 95, 172), (108, 153, 222), (210, 231, 254), (255, 255, 255)],
        "water_colors": [(12, 58, 129), (45, 95, 172), (108, 153, 222)],
        "water_tolerance": 0.09,     # how close a pixel's hue must be to a water color (smaller = stricter)
        "coast_margin_deg": 0.6,     # the mask reaches this far past every coast, so no shoreline pixels are read
        "max_color_distance": 60,    # a pixel further than this from the ramp is not data
        "value_range_percentiles": (40, 99.6),   # what counts as 0 and as 1, from all the values read
        "lat_range": (-48, 60),      # part of the line that is read (near the edges the globe is squashed, hazy and icy)
        "ignore_equator_px": 5,      # the equator is drawn as a line on the globe: skip it
        "globe": dict(_CAMERA),
        "sounds": {},
    },
    "temperature_currents": {
        "id": "temperature_currents",
        "title": "Ocean Currents in Color (spinning globe)",
        "source": "NASA Scientific Visualization Studio (ocean surface currents)",
        "description": (
            "A globe of the Earth turning once. The oceans are dark blue, and currents are drawn as streaks "
            "colored from purple through red and orange to bright yellow. The brightest yellow ribbons are "
            "the Gulf Stream, the Kuroshio off Japan and the eddies of the Caribbean. "
            "A line down the middle of the globe reads the colors as each ocean turns past it."
        ),
        "listening_guide": [
            "A line runs from north to south down the middle of the globe. The music is what passes under it.",
            "Each note is a bright current crossing the line. Higher = further north, lower = further south.",
            "Louder notes = brighter, yellower currents.",
            "The beat is the globe's spin: one beat for every 2 degrees it turns. When the globe slows down, so does the music.",
            "The soft wash is open water under the line. It fades when a continent passes.",
            "A bell rings every eighth of a turn, and the held chord changes every quarter turn.",
        ],
        "ramp": [(35, 45, 90), (140, 62, 76), (200, 100, 70), (230, 155, 70), (235, 205, 85)],
        "water_colors": [(12, 36, 60), (35, 45, 90), (60, 84, 108)],
        "water_tolerance": 0.09,
        "coast_margin_deg": 0.6,
        "max_color_distance": 60,
        "value_range_percentiles": (50, 98.5),
        "lat_range": (-48, 60),
        "ignore_equator_px": 5,
        "globe": dict(_CAMERA),
        "sounds": {
            "key": "E", "scale": "minor_pentatonic", "note_threshold": 0.15,
            "lowest_note": "E3", "highest_note": "E6", "chime_note": "E6",
            "chords": [(0, "min"), (-4, "maj"), (3, "maj"), (-2, "maj")],
        },
    },
}

LAYERS = ["notes", "pad", "sea", "chime"]
BIN_DEG = 2.0            # latitude bins along the line
LINE_HALF_WIDTH = 3      # the line reads this many pixels either side of the centre column
ALIGN_EVERY = 5          # the land map is lined up with the video every this many frames
LANDMASK_FILE = ROOT / "globe_landmask.png"
LANDMASK_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_land.geojson"

# =============================================================================
#  Geometry: how the camera sees the globe
# =============================================================================

def find_globe(cap, n_frames):
    """Centre and radius of the globe, from where the picture is not black."""
    boxes = []
    for i in np.linspace(0, max(n_frames - 1, 0), 8).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, f = cap.read()
        if not ok:
            continue
        ys, xs = np.nonzero(f.max(axis=2) > 24)
        if len(xs) > 1000:
            boxes.append((xs.min(), xs.max(), ys.min(), ys.max()))
    if not boxes:
        sys.exit("Could not find the globe: the video looks black.")
    x0, x1, y0, y1 = np.median(np.array(boxes), axis=0)
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    return (x0 + x1) / 2, (y0 + y1) / 2, ((x1 - x0) + (y1 - y0)) / 4


class Camera:
    """Turns a point on screen into a place on Earth, and back for points on the line."""

    def __init__(self, tilt_deg=0.0, distance=None, roll_deg=0.0):
        self.tilt, self.D, self.roll = float(tilt_deg), distance, float(roll_deg)
        vv = np.linspace(-0.999, 0.999, 4001)
        self._v = vv
        self._lat_on_line = self.surface(np.zeros_like(vv), vv)[0]      # latitude down the middle of the globe

    def surface(self, u, v):
        """u, v = position right of / above the globe's centre, in globe radii.
        Returns latitude, longitude relative to the point under the camera (degrees), and on-the-globe."""
        u, v = np.asarray(u, float), np.asarray(v, float)
        rr = u * u + v * v
        on = rr < 1
        cr, sr = np.cos(np.radians(self.roll)), np.sin(np.radians(self.roll))
        u, v = u * cr - v * sr, u * sr + v * cr
        if self.D:                                                       # camera at a finite distance
            k2 = self.D ** 2 - 1
            s = rr / k2
            z = (s * self.D + np.sqrt(np.maximum(1 + s - s * self.D ** 2, 0))) / (s + 1)
            x, y = u * (self.D - z) / np.sqrt(k2), v * (self.D - z) / np.sqrt(k2)
        else:                                                            # infinitely far away
            z = np.sqrt(np.maximum(1 - rr, 0))
            x, y = u, v
        t = np.radians(self.tilt)
        lat = np.degrees(np.arcsin(np.clip(y * np.cos(t) + z * np.sin(t), -1, 1)))
        dlon = np.degrees(np.arctan2(x, z * np.cos(t) - y * np.sin(t)))
        return lat, dlon, on

    def v_of_lat(self, lat):
        """Height on the line (in globe radii above the centre) of a latitude."""
        return np.interp(lat, self._lat_on_line, self._v)


# =============================================================================
#  The mask: a real map of the world's land, projected onto the globe
# =============================================================================

def load_landmask(coast_margin_deg=0.0):
    """Land (True) / water (False) for the whole Earth: longitude 180W..180E across, 90N..90S down.

    Read from globe_landmask.png next to this script. If that file is missing it is made once
    from Natural Earth's public-domain coastlines (downloaded from GitHub).
    """
    if not LANDMASK_FILE.exists():
        print(f"    {LANDMASK_FILE.name} not found: downloading the Natural Earth coastlines to make it...")
        import urllib.request
        try:
            with urllib.request.urlopen(LANDMASK_URL, timeout=60) as r:
                shapes = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            sys.exit(f"Could not download the land map ({e}). Put globe_landmask.png next to {Path(__file__).name}.")
        w, h = 4096, 2048
        m = np.zeros((h, w), np.uint8)
        polys = []
        for feat in shapes["features"]:
            g = feat["geometry"]
            polys += [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]

        def to_px(ring):
            p = np.array(ring, float)[:, :2]
            return np.stack([(p[:, 0] + 180) / 360 * w, (90 - p[:, 1]) / 180 * h], 1).round().astype(np.int32)
        for p in polys:
            cv2.fillPoly(m, [to_px(p[0])], 255)
        for p in polys:
            for hole in p[1:]:
                cv2.fillPoly(m, [to_px(hole)], 0)
        cv2.imwrite(str(LANDMASK_FILE), m, [cv2.IMWRITE_PNG_BILEVEL, 1])
    m = cv2.imread(str(LANDMASK_FILE), cv2.IMREAD_GRAYSCALE)
    if m is None:
        sys.exit(f"Can't read {LANDMASK_FILE}")
    m = (m > 127).astype(np.uint8)
    k = int(round(coast_margin_deg / 360 * m.shape[1]))
    if k > 0:                                                            # widen the land a little past the coast
        m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1)))
    return m.astype(bool)


def map_index(land, lat, dlon):
    """Where each screen point falls on the land map: fixed row, and column before the globe's turn is added."""
    mh, mw = land.shape
    yi = np.clip(((90 - lat) / 180 * mh).astype(np.int64), 0, mh - 1)
    xb = ((dlon + 180) / 360 * mw).astype(np.float32)
    return yi, xb


def land_at(land, yi, xb, lon0):
    """Is each screen point land, when longitude `lon0` is under the camera?"""
    mw = land.shape[1]
    return land[yi, (xb + lon0 * (mw / 360.0)).astype(np.int64) % mw]


# =============================================================================
#  Colors -> numbers
# =============================================================================

def build_lut(preset, bits=5):
    """For every (coarse) RGB color: position along the ramp (0..1), distance to the ramp,
    and whether it looks like plain water."""
    ramp = np.asarray(preset["ramp"], float)
    n = 1 << bits
    g = (np.arange(n) + 0.5) * (256 / n)
    P = np.stack(np.meshgrid(g, g, g, indexing="ij"), -1).reshape(-1, 3)
    best_d = np.full(len(P), 1e9)
    best_t = np.zeros(len(P))
    segs = len(ramp) - 1
    for i in range(segs):
        a, ab = ramp[i], ramp[i + 1] - ramp[i]
        u = np.clip(((P - a) @ ab) / (ab @ ab), 0, 1)
        d = np.linalg.norm(P - (a + u[:, None] * ab), axis=1)
        m = d < best_d
        best_d[m] = d[m]
        best_t[m] = (i + u[m]) / segs
    # plain water: same hue (color with the brightness divided out) as one of the water colors
    total = P.sum(axis=1)
    chroma = P / np.maximum(total, 1)[:, None]
    water = np.zeros(len(P), bool)
    for c in np.asarray(preset["water_colors"], float):
        water |= np.linalg.norm(chroma - c / c.sum(), axis=1) < preset["water_tolerance"]
    water &= total > 40                                      # not the black background
    shape = (n, n, n)
    return best_t.reshape(shape).astype(np.float32), best_d.reshape(shape).astype(np.float32), water.reshape(shape)


def classify(bgr, lut, bits=5):
    """Per pixel: value along the ramp, distance to the ramp, looks-like-plain-water."""
    q = bgr >> (8 - bits)
    i = (q[..., 2], q[..., 1], q[..., 0])
    return lut[0][i], lut[1][i], lut[2][i]


def water_by_color(base, scale=1.0):
    """Rough water / not-water picture of a frame from its colors alone. It is only used to line
    the land map up with the video (to find which longitude faces the camera); the mask itself
    is the map."""
    base = base.astype(np.uint8)
    k_close = max(3, int(round(19 * scale)) | 1)
    k_open = max(3, int(round(9 * scale)) | 1)
    m = cv2.morphologyEx(base, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_close, k_close)))
    return cv2.morphologyEx(m, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_open, k_open)))


# =============================================================================
#  1. Video analysis
# =============================================================================

def analyze(video, preset):
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        sys.exit(f"Can't open the video: {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cx, cy, R = find_globe(cap, n_total)
    g = preset["globe"]
    cam = Camera(g.get("tilt_deg", 0.0), g.get("distance"), g.get("roll_deg", 0.0))
    lut = build_lut(preset)
    land = load_landmask(preset.get("coast_margin_deg", 0.0))
    land_exact = load_landmask(0.0)

    # --- the line: the pixels down the middle of the globe, and where on Earth each one is
    xc = int(round(cx))
    cols = np.arange(xc - LINE_HALF_WIDTH, xc + LINE_HALF_WIDTH + 1)
    rows = np.arange(H)
    uu, vv = np.meshgrid((cols - cx) / R, (cy - rows) / R)
    lat_l, dlon_l, on_l = cam.surface(uu, vv)
    on_l &= (uu ** 2 + vv ** 2) < 0.985 ** 2
    yi_l, xb_l = map_index(land, lat_l, dlon_l)
    lat_rows = lat_l[:, LINE_HALF_WIDTH]
    lat_lo, lat_hi = preset["lat_range"]
    edges = np.arange(lat_lo, lat_hi + 1e-6, BIN_DEG)
    row_bin = np.digitize(lat_rows, edges) - 1
    row_ok = on_l[:, LINE_HALF_WIDTH] & (row_bin >= 0) & (row_bin < len(edges) - 1)
    eq = preset.get("ignore_equator_px", 0)
    if eq:
        row_ok &= np.abs(rows - (cy - cam.v_of_lat(0.0) * R)) > eq
    n_bins = len(edges) - 1
    bin_lat = (edges[:-1] + edges[1:]) / 2
    row_bin_ok = row_bin[row_ok]

    # --- a coarse grid over the whole globe, used to line the land map up with each frame
    ys, xs = np.mgrid[0:H:4, 0:W:4]
    ua, va = (xs - cx) / R, (cy - ys) / R
    lat_a, dlon_a, _ = cam.surface(ua, va)
    on_a = (ua ** 2 + va ** 2) < 0.90 ** 2
    yi_a, xb_a = map_index(land_exact, lat_a[on_a], dlon_a[on_a])

    def match(water_px, lon0):
        return (land_at(land_exact, yi_a, xb_a, lon0) != water_px).mean()

    # --- patch at the centre of the globe: how far the surface moves between frames
    ph, pw = int(R * 0.24), int(R * 0.48)
    py0, px0 = int(cy) - ph, int(cx) - pw
    px_per_deg = np.radians(1) * R * np.cos(np.radians(cam.tilt)) * (
        np.sqrt(cam.D ** 2 - 1) / (cam.D - 1) if cam.D else 1.0)
    win = prev = None
    moved = 0.0

    line_t = np.zeros((n_total, H, len(cols)), np.float16)
    line_ok = np.zeros((n_total, H, len(cols)), bool)
    align_frames, align_lon, align_score = [], [], []
    n = 0
    while n < n_total:
        ok, f = cap.read()
        if not ok:
            break
        t, d, _ = classify(f[:, cols[0]:cols[-1] + 1], lut)
        line_t[n] = t
        line_ok[n] = d < preset["max_color_distance"]

        gray = cv2.cvtColor(f[py0:py0 + 2 * ph, px0:px0 + 2 * pw], cv2.COLOR_BGR2GRAY).astype(np.float32)
        if win is None:
            win = cv2.createHanningWindow((gray.shape[1], gray.shape[0]), cv2.CV_32F)
        if prev is not None:
            (sx, _), _ = cv2.phaseCorrelate(prev, gray, win)
            moved += sx / px_per_deg                         # the surface moves right = the longitude goes down
        prev = gray

        if n % ALIGN_EVERY == 0:
            small = cv2.resize(f, (xs.shape[1] * 2, xs.shape[0] * 2), interpolation=cv2.INTER_AREA)
            water_px = water_by_color(classify(small, lut)[2], scale=0.5).astype(bool)[::2, ::2][on_a]
            if not align_lon:                                # first frame: try every longitude
                cands = np.arange(-180, 180, 1.5)
                best = cands[int(np.argmax([match(water_px, c) for c in cands]))]
                cands = best + np.arange(-1.5, 1.51, 0.25)
            else:                                            # afterwards: look near where the turn should have taken it
                cands = align_lon[-1] - moved + np.arange(-2.5, 2.51, 0.25)
            scores = [match(water_px, c) for c in cands]
            j = int(np.argmax(scores))
            align_frames.append(n)
            align_lon.append(float(cands[j]))
            align_score.append(float(scores[j]))
            moved = 0.0
        n += 1
        if n % 500 == 0:
            print(f"    {n}/{n_total} frames")
    cap.release()
    line_t, line_ok = line_t[:n], line_ok[:n]

    # longitude under the camera for every frame (kept continuous, so it can go beyond +-180)
    al = np.array(align_lon)
    if len(al) >= 5:
        al = signal.medfilt(al, 5)
        al[[0, 1, -2, -1]] = np.array(align_lon)[[0, 1, -2, -1]]
    lon = smooth(np.interp(np.arange(n), align_frames, al), 2 * ALIGN_EVERY + 1)

    # --- read the line: mask with the map, then average the values per latitude bin
    tot_cnt = np.bincount(row_bin_ok, minlength=n_bins)[:n_bins].astype(np.float32) * len(cols)
    val = np.full((n, n_bins), np.nan, np.float32)
    frac = np.zeros((n, n_bins), np.float32)
    for i in range(n):
        water = ~land_at(land, yi_l, xb_l, lon[i]) & row_ok[:, None]
        good = water & line_ok[i]
        w_cnt = np.bincount(row_bin_ok, weights=water.sum(axis=1)[row_ok], minlength=n_bins)[:n_bins]
        g_cnt = np.bincount(row_bin_ok, weights=good.sum(axis=1)[row_ok], minlength=n_bins)[:n_bins]
        g_sum = np.bincount(row_bin_ok, weights=np.where(good, line_t[i], 0).sum(axis=1)[row_ok], minlength=n_bins)[:n_bins]
        frac[i] = w_cnt / np.maximum(tot_cnt, 1)
        val[i] = np.where(g_cnt > 0, g_sum / np.maximum(g_cnt, 1), np.nan)
    return {"fps": fps, "n": n, "W": W, "H": H, "cx": cx, "cy": cy, "R": R, "bin_lat": bin_lat,
            "val": val, "frac": frac, "lon": lon.astype(np.float32),
            "map_match": float(np.median(align_score)) if align_score else 0.0}


def load_or_analyze(video, preset, out, force):
    cache = out / "analysis.npz"
    st = video.stat()
    g = preset["globe"]
    key = json.dumps([video.name, st.st_size, int(st.st_mtime), preset["ramp"], preset["water_colors"],
                      preset["water_tolerance"], preset["max_color_distance"], preset["lat_range"],
                      preset.get("ignore_equator_px"), preset.get("coast_margin_deg"),
                      g.get("tilt_deg"), g.get("distance"), g.get("roll_deg"), "map-v1"], default=str)
    if cache.exists() and not force:
        z = np.load(cache, allow_pickle=False)
        if str(z["key"]) == key:
            print("1/5 Using cached video analysis (--reanalyze to redo it)")
            return {k: (z[k] if z[k].ndim else z[k].item()) for k in z.files if k != "key"}
    print("1/5 Reading the video: lining the land map up with the globe and reading the line (about a minute)...")
    a = analyze(video, preset)
    np.savez_compressed(cache, key=key, **a)
    return a


# =============================================================================
#  2. Rotation -> beats, line -> notes
# =============================================================================

def nanmean(x, axis):
    """np.nanmean without the warning when a whole row is masked."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmean(x, axis=axis)


def smooth(x, k):
    if k <= 1:
        return x
    pad = np.pad(x, (k // 2, k - 1 - k // 2), mode="edge")
    return np.convolve(pad, np.ones(k) / k, mode="valid")


def build_timeline(a, preset, snd):
    g = preset["globe"]
    cam = Camera(g.get("tilt_deg", 0.0), g.get("distance"), g.get("roll_deg", 0.0))
    fps, n = float(a["fps"]), int(a["n"])
    t = np.arange(n) / fps
    # the longitude facing the camera, frame by frame, tells how far the globe has turned
    lon_cont = a["lon"].astype(float)
    direction = 1.0 if lon_cont[-1] >= lon_cont[0] else -1.0
    theta = np.maximum.accumulate(direction * (lon_cont - lon_cont[0]))   # total rotation so far, never goes back
    deg = np.gradient(theta)
    lon = ((lon_cont + 180) % 360) - 180
    step_lon_src = lon_cont

    # values 0..1
    lo, hi = np.nanpercentile(a["val"][a["frac"] >= 0.5], preset["value_range_percentiles"])
    strength = np.clip((a["val"] - lo) / max(hi - lo, 1e-6), 0, 1)
    strength = np.where(a["frac"] >= 0.5, strength, np.nan)   # a bin counts when at least half of it is water

    # one beat per `degrees_per_step` of rotation
    step_deg = snd["degrees_per_step"]
    n_steps = int(theta[-1] // step_deg) + 1
    step_of_frame = np.minimum((theta // step_deg).astype(int), n_steps - 1)
    step_time = np.interp(np.arange(n_steps) * step_deg, theta, t)
    P = np.full((n_steps, strength.shape[1]), np.nan, np.float32)
    water = np.zeros(n_steps, np.float32)
    for k in range(n_steps):
        idx = np.flatnonzero(step_of_frame == k)
        if len(idx) == 0:                                    # the globe turned more than one step in a frame
            idx = [int(np.searchsorted(theta, k * step_deg).clip(0, n - 1))]
        P[k] = nanmean(strength[idx], axis=0)
        water[k] = a["frac"][idx].mean()
    step_lon = None if step_lon_src is None else ((np.interp(step_time, t, step_lon_src) + 180) % 360) - 180
    return {"t": t, "deg_per_frame": deg, "theta": theta, "lon": lon, "step_lon": step_lon, "strength": strength,
            "n_steps": n_steps, "step_time": step_time, "P": P, "water": water,
            "duration": n / fps, "fps": fps, "n": n, "cam": cam, "value_range": (float(lo), float(hi))}


def pick_notes(tl, a, snd):
    """On each beat: the strongest currents under the line, at most `max_notes`, well apart."""
    P = tl["P"]
    bin_lat = a["bin_lat"]
    sep = max(int(round(snd["min_separation_deg"] / BIN_DEG)), 1)
    last_step = {}
    last_val = {}
    events = []
    for k in range(tl["n_steps"]):
        row = np.nan_to_num(P[k], nan=0.0)
        sm = np.convolve(np.pad(row, 1, mode="edge"), [0.25, 0.5, 0.25], mode="valid")
        cand = [b for b in range(len(sm)) if sm[b] >= snd["note_threshold"]
                and sm[b] >= sm[max(b - 1, 0)] and sm[b] >= sm[min(b + 1, len(sm) - 1)] and not np.isnan(P[k, b])]
        cand.sort(key=lambda b: -sm[b])
        chosen = []
        for b in cand:
            if len(chosen) >= snd["max_notes"]:
                break
            if all(abs(b - c) >= sep for c in chosen):
                chosen.append(b)
        for b in chosen:
            zone = b // 2
            held = zone in last_step and k - last_step[zone] < snd["hold_steps"]
            if held and sm[b] < last_val[zone] * 1.3:
                continue                                      # still the same current: let it ring
            last_step[zone], last_val[zone] = k, sm[b]
            events.append({"step": k, "time": float(tl["step_time"][k]), "bin": b,
                           "lat": float(bin_lat[b]), "strength": float(sm[b])})
    return events


# =============================================================================
#  3. Sound
# =============================================================================

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
SCALES = {
    "major_pentatonic": [0, 2, 4, 7, 9], "minor_pentatonic": [0, 3, 5, 7, 10],
    "major": [0, 2, 4, 5, 7, 9, 11], "minor": [0, 2, 3, 5, 7, 8, 10],
    "dorian": [0, 2, 3, 5, 7, 9, 10], "lydian": [0, 2, 4, 6, 7, 9, 11],
}


def note_to_midi(name):
    name = name.strip()
    letter, rest = name[0].upper(), name[1:]
    acc = 0
    if rest[:1] in "#b":
        acc = 1 if rest[0] == "#" else -1
        rest = rest[1:]
    return 12 * (int(rest) + 1) + NOTE_NAMES.index(letter) + acc


def midi_to_hz(m):
    return 440.0 * 2 ** ((np.asarray(m, float) - 69) / 12)


def notes_in_range(key, scale, low, high):
    root = NOTE_NAMES.index(key)
    return [m for m in range(note_to_midi(low), note_to_midi(high) + 1) if (m - root) % 12 in SCALES[scale]]


def make_note(freq, instrument):
    """One struck note, mono."""
    if instrument == "glass":
        # soft and slow: a breath of attack, a long ring, and two slightly detuned copies that shimmer
        t = np.arange(int(4.5 * SR)) / SR
        out = np.zeros(len(t))
        for cents in (-5, 5):
            f = freq * 2 ** (cents / 1200)
            for ratio, amp, decay in ((1.0, 1.0, 0.9), (2.0, 0.22, 1.4), (3.0, 0.07, 2.0), (4.0, 0.03, 2.8)):
                if f * ratio < SR / 2.2:
                    out += amp * np.sin(2 * np.pi * f * ratio * t) * np.exp(-decay * t)
        attack = int(0.06 * SR)
        out[:attack] *= np.sin(np.linspace(0, np.pi / 2, attack)) ** 2
        out[-2000:] *= np.linspace(1, 0, 2000)
        return out / (np.abs(out).max() + 1e-9)
    if instrument == "bell":
        dur, parts = 3.0, [(1.0, 1.0, 1.4), (2.76, 0.5, 2.2), (5.4, 0.3, 3.5), (8.93, 0.15, 5.0)]
    elif instrument == "pluck":
        dur, parts = 1.6, [(k, 1.0 / k, 2.2 + 1.3 * k) for k in range(1, 8)]
    else:  # marimba
        dur, parts = 1.3, [(1.0, 1.0, 4.0), (4.0, 0.35, 9.0), (10.0, 0.12, 18.0)]
    t = np.arange(int(dur * SR)) / SR
    out = np.zeros(len(t))
    for ratio, amp, decay in parts:
        if freq * ratio < SR / 2.2:
            out += amp * np.sin(2 * np.pi * freq * ratio * t) * np.exp(-decay * t)
    attack = int(0.004 * SR)
    out[:attack] *= np.linspace(0, 1, attack)
    out[-200:] *= np.linspace(1, 0, 200)
    return out / (np.abs(out).max() + 1e-9)


def add_mono(buf, mono, start_s, pan=0.0, gain=1.0):
    i0 = int(start_s * SR)
    if i0 >= len(buf):
        return
    seg = mono[: len(buf) - i0] * gain
    a = (np.clip(pan, -1, 1) + 1) * np.pi / 4
    buf[i0:i0 + len(seg), 0] += seg * np.cos(a)
    buf[i0:i0 + len(seg), 1] += seg * np.sin(a)


def pad_voice(freq, amp, harmonics=(1.0, 0.3, 0.12, 0.04), detune_cents=7):
    """Warm held tone; amp is given per sample."""
    out = np.zeros(len(amp))
    t = np.arange(len(amp)) / SR
    for dc in (-detune_cents, detune_cents):
        f = freq * 2 ** (dc / 1200)
        for k, h in enumerate(harmonics, start=1):
            out += h * np.sin(2 * np.pi * f * k * t)
    return out * amp / (2 * sum(harmonics))


def glide(x, seconds):
    """Smooth a per-sample control signal."""
    k = np.exp(-1 / max(seconds * SR, 1))
    return signal.lfilter([1 - k], [1, -k], x, zi=[x[0] * k])[0]


def reverb(stereo, seconds, wet, seed=7):
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    env = np.exp(-np.arange(n) / SR * 6.9 / seconds)
    lp = signal.butter(1, 5000, "lowpass", fs=SR, output="sos")
    out = np.zeros_like(stereo)
    for ch in range(2):
        ir = signal.sosfilt(lp, rng.standard_normal(n)) * env
        ir /= np.sqrt((ir ** 2).sum())
        out[:, ch] = signal.fftconvolve(stereo[:, ch], ir)[: len(stereo)]
    return (1 - wet) * stereo + wet * out


def render_audio(tl, a, events, snd, only=None):
    n = int((tl["duration"] + snd["tail_seconds"]) * SR)
    ts = np.arange(n) / SR
    end = tl["duration"]
    fade = np.clip(1 - (ts - end) / (snd["tail_seconds"] * 0.8), 0, 1) * np.clip(ts / 0.5, 0, 1)
    active = [l for l in LAYERS if not only or l in only]
    stems = {}
    lat_lo, lat_hi = a["bin_lat"][0], a["bin_lat"][-1]

    if "notes" in active:
        scale = notes_in_range(snd["key"], snd["scale"], snd["lowest_note"], snd["highest_note"])
        cache = {}
        buf = np.zeros((n, 2))
        for e in events:
            pos = (e["lat"] - lat_lo) / (lat_hi - lat_lo)                 # 0 = south end, 1 = north end
            m = scale[int(round(pos * (len(scale) - 1)))]
            if m not in cache:
                cache[m] = make_note(midi_to_hz(m), snd["instrument"])
            loud = snd["quiet"] + (snd["loud"] - snd["quiet"]) * e["strength"] ** 0.8
            add_mono(buf, cache[m], e["time"], pan=-(pos * 2 - 1) * snd["stereo_width"], gain=loud)
            e["midi"] = int(m)
        if snd.get("echo_seconds", 0) > 0:                   # echoes that swap sides each time
            dry = buf.copy()
            for rep_i in (1, 2, 3):
                shift = int(rep_i * snd["echo_seconds"] * SR)
                if shift < n:
                    src = dry[:, ::-1] if rep_i % 2 else dry
                    buf[shift:] += src[: n - shift] * snd["echo_gain"] ** rep_i
        stems["notes"] = buf

    # how strong the currents under the line are, and how much of the line is water, per sample
    mean_strength = np.nan_to_num(nanmean(tl["strength"], axis=1), nan=0.0)
    water = a["frac"].mean(axis=1)
    k_s = max(int(tl["fps"] * 0.5), 1)
    strength_s = glide(np.interp(ts, tl["t"], smooth(mean_strength, k_s)), 0.4)
    water_s = glide(np.interp(ts, tl["t"], smooth(water, k_s)), 0.4)

    if "pad" in active:
        root = NOTE_NAMES.index(snd["key"]) + 12 * (snd["chord_octave"] + 1)
        theta_s = np.interp(ts, tl["t"], tl["theta"])
        chord_idx = (theta_s // snd["chord_every_deg"]).astype(int) % len(snd["chords"])
        level = (0.35 + 0.65 * strength_s / (strength_s.max() + 1e-9)) * (0.3 + 0.7 * water_s) * fade
        tone = np.zeros(n)
        for ci, (off, kind) in enumerate(snd["chords"]):
            gate = glide((chord_idx == ci).astype(float), 0.5)
            if gate.max() < 1e-3:
                continue
            third = 4 if kind == "maj" else 3
            for semis, g in ((0, 1.0), (7, 0.7), (12, 0.6), (12 + third, 0.45)):
                tone += pad_voice(midi_to_hz(root + off + semis), gate * level * g)
            # high overtones that slowly breathe in and out
            breathe = 0.5 + 0.5 * np.sin(2 * np.pi * 0.09 * ts + ci)
            for semis in (24, 31):
                tone += pad_voice(midi_to_hz(root + off + semis), gate * level * breathe * snd.get("pad_shimmer", 0),
                                  harmonics=(1.0, 0.1))
        stems["pad"] = np.stack([tone, np.roll(tone, int(0.011 * SR))], axis=1)

    if "sea" in active:
        rng = np.random.default_rng(3)
        bp = signal.butter(2, [350, 2600], "bandpass", fs=SR, output="sos")
        env = water_s ** 1.5 * fade
        stems["sea"] = np.stack([signal.sosfilt(bp, rng.standard_normal(n)) * env for _ in range(2)], axis=1)

    if "chime" in active:
        m = note_to_midi(snd["chime_note"])
        bell = make_note(midi_to_hz(m), "bell")
        fifth = make_note(midi_to_hz(m + 7), "bell")
        bell = bell + 0.5 * fifth
        buf = np.zeros((n, 2))
        marks = np.arange(0, tl["theta"][-1], snd["chime_every_deg"])
        for i, th in enumerate(marks):
            add_mono(buf, bell, float(np.interp(th, tl["theta"], tl["t"])), gain=1.0 if i % 2 == 0 else 0.6)
        stems["chime"] = buf

    if not stems:
        sys.exit("No layers left to play.")
    stems = {k: reverb(s * snd["volumes"][k], snd["reverb_seconds"], snd["reverb_wet"]) for k, s in stems.items()}
    mix = sum(stems.values())
    k = snd["peak"] / (np.abs(np.tanh(mix * 1.2)).max() + 1e-9)
    audio = (np.tanh(mix * 1.2) * k).astype(np.float32)
    return audio, {name: (s * 1.2 * k).astype(np.float32) for name, s in stems.items()}


# =============================================================================
#  4. Plot, CSV, descriptions
# =============================================================================

def ocean_name(lon):
    if lon is None:
        return None
    if -70 <= lon < 20:
        return "the Atlantic Ocean"
    if 20 <= lon < 120:
        return "the Indian Ocean"
    return "the Pacific Ocean"


def lat_text(lat):
    return "the equator" if abs(lat) < 3 else f"{abs(lat):.0f} degrees {'north' if lat > 0 else 'south'}"


def write_plot(tl, a, events, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 8), gridspec_kw={"height_ratios": [3, 1]}, constrained_layout=True)
    P = np.ma.masked_invalid(tl["P"].T)
    cmap = plt.get_cmap("inferno").copy()
    cmap.set_bad("#9a9a9a")
    step = tl["theta"][-1] / max(tl["n_steps"], 1)
    ext = [0, tl["n_steps"] * step, a["bin_lat"][0] - BIN_DEG / 2, a["bin_lat"][-1] + BIN_DEG / 2]
    im = ax1.imshow(P, origin="lower", aspect="auto", extent=ext, cmap=cmap, vmin=0, vmax=1)
    if events:
        ax1.scatter([(e["step"] + 0.5) * step for e in events], [e["lat"] for e in events],
                    s=[10 + 50 * e["strength"] for e in events], facecolors="none", edgecolors="#7CFFCB", linewidths=0.8)
    ax1.set_ylabel("Latitude on the line")
    ax1.set_xlabel("Rotation of the globe (degrees)")
    ax1.set_title("What passed under the line: current strength (grey = masked land / ice), circles = notes played")
    fig.colorbar(im, ax=ax1, label="Strength (0..1)", pad=0.01)
    ax2.plot(tl["t"], np.abs(tl["deg_per_frame"]) * tl["fps"], color="#1f77b4")
    ax2.set_ylabel("Spin (degrees / second)", color="#1f77b4")
    ax2.set_xlabel("Time in the video (seconds)")
    ax3 = ax2.twinx()
    ax3.plot(tl["t"], a["frac"].mean(axis=1) * 100, color="#2ca02c", alpha=0.7)
    ax3.set_ylabel("Water under the line (%)", color="#2ca02c")
    ax3.set_ylim(0, 100)
    ax2.set_title("The spin sets the beat; water under the line sets the wash")
    fig.savefig(path, dpi=110)
    plt.close(fig)


def write_csv(tl, a, events, path):
    by_step = {}
    for e in events:
        by_step.setdefault(e["step"], []).append(e)
    with open(path, "w", encoding="utf-8") as f:
        f.write("step,time_s,rotation_deg,longitude,water_percent,mean_strength,max_strength,notes\n")
        for k in range(tl["n_steps"]):
            row = tl["P"][k]
            ok = ~np.isnan(row)
            lon = "" if tl["step_lon"] is None else f"{tl['step_lon'][k]:.1f}"
            notes = " ".join(f"{e['lat']:+.0f}:{e['strength']:.2f}" for e in by_step.get(k, []))
            f.write(f"{k},{tl['step_time'][k]:.3f},{k * tl['theta'][-1] / max(tl['n_steps'], 1):.1f},{lon},"
                    f"{tl['water'][k] * 100:.0f},{row[ok].mean() if ok.any() else 0:.3f},"
                    f"{row[ok].max() if ok.any() else 0:.3f},{notes}\n")


def vtt_time(s):
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{sec:06.3f}"


def write_vtt(tl, a, events, snd, path, segment_deg=45):
    """One sentence per eighth of a turn."""
    theta, t = tl["theta"], tl["t"]
    cues = []
    marks = list(np.arange(0, theta[-1], segment_deg)) + [theta[-1]]
    for i in range(len(marks) - 1):
        t0, t1 = float(np.interp(marks[i], theta, t)), float(np.interp(marks[i + 1], theta, t))
        if i == len(marks) - 2:
            t1 = tl["duration"]
        if t1 - t0 < 0.3:
            continue
        f0, f1 = int(t0 * tl["fps"]), max(int(t1 * tl["fps"]), int(t0 * tl["fps"]) + 1)
        water = a["frac"][f0:f1].mean() * 100
        seg = tl["strength"][f0:f1]
        prof = nanmean(seg, axis=0)
        text = f"Turn {marks[i]:.0f} to {marks[i + 1]:.0f} degrees. "
        if tl["lon"] is not None:
            text += (f"The line is over {ocean_name(float(tl['lon'][(f0 + f1) // 2]))}. " if water >= 45
                     else "The line is mostly over land. ")
        text += f"{water:.0f}% of the line is water. "
        n_notes = sum(1 for e in events if t0 <= e["time"] < t1)
        if np.isfinite(prof).any() and np.nanmax(prof) >= snd["note_threshold"]:
            text += f"Strongest current near {lat_text(float(a['bin_lat'][int(np.nanargmax(prof))]))}; {n_notes} notes."
        else:
            text += "No strong currents: only the held chord."
        spin = (marks[i + 1] - marks[i]) / max(t1 - t0, 1e-6)
        if i == len(marks) - 2 and spin < 1.5:
            text += " The globe slows to a stop and the music winds down."
        cues.append((t0, t1, text))
    with open(path, "w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n")
        for i, (t0, t1, text) in enumerate(cues, start=1):
            f.write(f"{i}\n{vtt_time(t0)} --> {vtt_time(t1)}\n{text}\n\n")
    return cues


# =============================================================================
#  5. Video: mask, line and note markers drawn on the original
# =============================================================================

def render_video(video, wav, out_path, preset, a, tl, events, audio_seconds, plain=False, out_height=720):
    if not shutil.which("ffmpeg"):
        print("! ffmpeg not found: skipping the video. Install it (e.g. `winget install ffmpeg`) and run again.")
        return False
    cap = cv2.VideoCapture(str(video))
    W, H, fps = int(a["W"]), int(a["H"]), float(a["fps"])
    cx, cy, R = float(a["cx"]), float(a["cy"]), float(a["R"])
    cam = tl["cam"]
    land = load_landmask(0.0)
    lon = a["lon"].astype(float)
    xc = int(round(cx))
    y_top, y_bot = int(cy - 0.985 * R), int(cy + 0.985 * R)
    lat_lo, lat_hi = preset["lat_range"]
    y_read0, y_read1 = int(cy - cam.v_of_lat(lat_hi) * R), int(cy - cam.v_of_lat(lat_lo) * R)
    # where every (half-size) pixel of the globe is on Earth, for projecting the land map
    ys, xs = np.mgrid[0:H:2, 0:W:2]
    ug, vg = (xs - cx) / R, (cy - ys) / R
    lat_g, dlon_g, _ = cam.surface(ug, vg)
    on_g = (ug ** 2 + vg ** 2) < 0.995 ** 2
    yi_g, xb_g = map_index(land, lat_g[on_g], dlon_g[on_g])
    land_small = np.zeros(on_g.shape, np.uint8)
    ev_frames = sorted(((int(e["time"] * fps), e) for e in events), key=lambda x: x[0])
    out_height = min(out_height or H, H)
    out_w = int(round(W * out_height / H / 2)) * 2
    out_size = (out_w, int(out_height // 2) * 2)
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{out_size[0]}x{out_size[1]}", "-r", f"{fps}", "-i", "-",
           "-i", str(wav), "-map", "0:v:0", "-map", "1:a:0",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", str(out_path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n_out = int(np.ceil(audio_seconds * fps))
    last = None
    ev_i = 0
    live = []
    ring_frames = int(0.5 * fps)
    for i in range(n_out):
        ok, f = cap.read() if i < int(a["n"]) else (False, None)
        if not ok:
            f = last.copy() if last is not None else np.zeros((H, W, 3), np.uint8)
        else:
            if not plain:
                # the mask: land from the map is dimmed and greyed
                land_small[on_g] = land_at(land, yi_g, xb_g, lon[min(i, len(lon) - 1)])
                is_land = cv2.resize(land_small, (W, H), interpolation=cv2.INTER_LINEAR).astype(bool)
                grey = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
                f[is_land] = (grey[is_land][:, None] * 0.3).astype(np.uint8)
            last = f.copy()
        # the line
        over = f.copy()
        cv2.line(over, (xc, y_top), (xc, y_bot), (255, 255, 255), 1, cv2.LINE_AA)
        cv2.line(over, (xc, y_read0), (xc, y_read1), (255, 255, 255), 3, cv2.LINE_AA)
        f = cv2.addWeighted(over, 0.75, f, 0.25, 0)
        # note markers: a ring that grows and fades where each note was read
        while ev_i < len(ev_frames) and ev_frames[ev_i][0] <= i:
            live.append(ev_frames[ev_i])
            ev_i += 1
        live = [(fr, e) for fr, e in live if i - fr < ring_frames]
        for fr, e in live:
            age = (i - fr) / ring_frames
            y = int(cy - cam.v_of_lat(e["lat"]) * R)
            rad = int(7 + 30 * age * (0.5 + e["strength"]))
            ya, yb, xa, xb = max(y - rad - 4, 0), min(y + rad + 5, H), max(xc - rad - 4, 0), min(xc + rad + 5, W)
            roi = f[ya:yb, xa:xb]
            ring = roi.copy()
            cv2.circle(ring, (xc - xa, y - ya), rad, (203, 255, 124), 2, cv2.LINE_AA)
            if age < 0.25:
                cv2.circle(ring, (xc - xa, y - ya), 5, (255, 255, 255), -1, cv2.LINE_AA)
            f[ya:yb, xa:xb] = cv2.addWeighted(ring, 1 - age, roi, age, 0)
        if out_size != (W, H):
            f = cv2.resize(f, out_size, interpolation=cv2.INTER_AREA)
        try:
            proc.stdin.write(f.tobytes())
        except BrokenPipeError:
            break
        if (i + 1) % 500 == 0:
            print(f"    {i + 1}/{n_out} frames")
    cap.release()
    proc.stdin.close()
    return proc.wait() == 0


def update_tracks(preset, has_video):
    path = ROOT / "website" / "tracks.json"
    tracks = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    pid = preset["id"]
    old = next((t for t in tracks if t["id"] == pid), {})
    entry = {"id": pid, "title": preset["title"], "source": preset["source"],
             "description": preset["description"], "listening_guide": preset["listening_guide"],
             "video": f"media/{pid}.mp4" if has_video else old.get("video"),
             "captions": f"media/{pid}.vtt", "features_image": f"media/{pid}.png"}
    tracks = [t for t in tracks if t["id"] != pid] + [entry]
    path.write_text(json.dumps(tracks, indent=2), encoding="utf-8")


# =============================================================================

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("preset", choices=sorted(PRESETS))
    ap.add_argument("video")
    ap.add_argument("--only", help=f"comma-separated layers to keep ({', '.join(LAYERS)})")
    ap.add_argument("--stems", action="store_true", help="also save every layer as its own WAV")
    ap.add_argument("--no-video", action="store_true", help="don't build the video")
    ap.add_argument("--plain-video", action="store_true", help="draw the line and notes, but don't dim the masked land")
    ap.add_argument("--video-height", type=int, default=720, help="height of the output video in pixels (default 720; 0 = same as the source)")
    ap.add_argument("--reanalyze", action="store_true", help="ignore the cached video analysis")
    ap.add_argument("--website", action="store_true", help="copy the results to website/media and add the track to website/tracks.json")
    args = ap.parse_args()

    preset = PRESETS[args.preset]
    snd = {**DEFAULT_SOUNDS, **preset.get("sounds", {})}
    snd["volumes"] = {**DEFAULT_SOUNDS["volumes"], **preset.get("sounds", {}).get("volumes", {})}
    video = Path(args.video)
    if not video.exists():
        sys.exit(f"Video not found: {video}")
    only = None
    if args.only:
        only = [s.strip() for s in args.only.split(",") if s.strip()]
        bad = [s for s in only if s not in LAYERS]
        if bad:
            sys.exit(f"--only: unknown layer(s) {', '.join(bad)}. Choose from: {', '.join(LAYERS)}")
    out = ROOT / "output" / preset["id"]
    out.mkdir(parents=True, exist_ok=True)

    a = load_or_analyze(video, preset, out, args.reanalyze)
    tl = build_timeline(a, preset, snd)
    events = pick_notes(tl, a, snd)
    print(f"    globe at ({a['cx']:.0f}, {a['cy']:.0f}), radius {a['R']:.0f} px; the land map matches {a['map_match'] * 100:.0f}% of the picture")
    print(f"    the globe turns {tl['theta'][-1]:.0f} degrees "
          f"in {tl['duration']:.1f} s -> {tl['n_steps']} beats, {len(events)} notes")

    print("2/5 Composing the soundtrack" + (f" (only: {', '.join(only)})" if only else "") + "...")
    audio, stems = render_audio(tl, a, events, snd, only=only)
    wavfile.write(out / "sonification.wav", SR, audio)
    if args.stems:
        (out / "stems").mkdir(exist_ok=True)
        for name, s in stems.items():
            wavfile.write(out / "stems" / f"{name}.wav", SR, s)
        print(f"    stems: {', '.join(stems)} -> {out / 'stems'}")

    print("3/5 Plotting what the line read, and writing the CSV...")
    write_plot(tl, a, events, out / "features.png")
    write_csv(tl, a, events, out / "features.csv")

    print("4/5 Writing descriptions...")
    write_vtt(tl, a, events, snd, out / "descriptions.vtt")

    has_video = False
    mp4 = out / f"{preset['id']}.mp4"
    if args.no_video:
        print("5/5 Skipping the video (--no-video)")
    elif only:
        print("5/5 Skipping the video (--only is for testing)")
    else:
        print("5/5 Building the video with the mask, the line and the notes (a few minutes)...")
        has_video = render_video(video, out / "sonification.wav", mp4, preset, a, tl, events,
                                 len(audio) / SR, plain=args.plain_video, out_height=args.video_height)
    if args.website:
        media = ROOT / "website" / "media"
        media.mkdir(parents=True, exist_ok=True)
        if has_video:
            shutil.copy(mp4, media / f"{preset['id']}.mp4")
        shutil.copy(out / "descriptions.vtt", media / f"{preset['id']}.vtt")
        shutil.copy(out / "features.png", media / f"{preset['id']}.png")
        update_tracks(preset, has_video or (media / f"{preset['id']}.mp4").exists())
        print("    added to website/tracks.json")
    print(f"Done. Listen to {out / 'sonification.wav'}" + (f" or watch {mp4}" if has_video else ""))


if __name__ == "__main__":
    sys.exit(main())
