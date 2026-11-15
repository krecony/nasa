"""Tracks: one folder per visualization, under tracks/.

    tracks/<name>/
        track.toml     what the video is: title, description, dates, colors, ...
        sounds.toml    how it sounds: instruments, samples, volumes, mappings
        colorbar.png   the color bar image (for "field" tracks)
        <video>.mp4    the original NASA video (not in git: too big)
        samples/       optional: WAV files only this track uses

The folder name is the track's id: it's used in commands (py sonify.py WindSpeed)
and file names (website/media/WindSpeed.mp4).

load_track() turns a folder into the settings dictionary the engine uses.
"""

from pathlib import Path

from .config import tomllib

ROOT = Path(__file__).resolve().parent.parent
TRACKS_DIR = ROOT / "tracks"
VIDEO_TYPES = (".mp4", ".mov", ".webm", ".m4v")
# settings that change what the video analysis finds (a change means: read the video again)
ANALYSIS_KEYS = ["kind", "map", "layers", "color_match", "min_background_diff", "ignore", "heavy_threshold",
                 "colorbar", "max_color_distance", "color_space", "unmatched_value", "hot_threshold", "cold_threshold",
                 "very_cold_threshold"]

# every setting a track.toml can have, with its default (None = required)
KNOWN = {
    "title": None, "source": "", "description": "", "listening_guide": [],
    "kind": "field", "video": "",
    "start_time": None, "hours_per_frame": None, "slow_down": 1.5, "smooth_video": False,
    "ignore": [], "map": {"lon_min": -180, "lon_max": 180, "lat_max": 90, "lat_min": -90},
    # field tracks (a value everywhere: temperature, wind, ...)
    "colorbar": None, "units": "", "max_color_distance": 40, "color_space": "rgb", "unmatched_value": None,
    "hot_threshold": None, "cold_threshold": None, "very_cold_threshold": None,
    # words for the daily captions (field tracks)
    "caption_high": "Highest", "caption_low": "Lowest outside Antarctica",
    "caption_share": "", "caption_share_name": "That share",
    # categories tracks (data only where something happens, color bar inside the video: rain)
    "layers": None, "color_match": {"min_sat": 0.45, "min_val": 0.35, "max_hue_dist": 25},
    "min_background_diff": 45, "heavy_threshold": 10.0,
}
NEEDED = {"field": ["colorbar", "hot_threshold", "cold_threshold", "very_cold_threshold"],
          "categories": ["layers"]}


def track_dir(name_or_path):
    """'WindSpeed', 'tracks/WindSpeed' or a full path -> the track folder."""
    p = Path(name_or_path)
    for cand in (p, TRACKS_DIR / p.name, ROOT / p):
        if (cand / "track.toml").exists():
            return cand.resolve()
    have = ", ".join(all_track_names()) or "none yet"
    raise SystemExit(f"No track called '{name_or_path}'. Tracks: {have}")


def all_track_names():
    if not TRACKS_DIR.exists():
        return []
    return sorted(d.name for d in TRACKS_DIR.iterdir()
                  if (d / "track.toml").exists() and not d.name.startswith(("_", ".")))


def find_video(folder, cfg, override=None):
    """The video: --video if given, else track.toml's `video` (in the track folder or videos/),
    else the only video file in the track folder."""
    if override:
        p = Path(override)
        if not p.exists():
            raise SystemExit(f"Video not found: {p}")
        return p.resolve()
    name = cfg.get("video") or ""
    if name:
        for cand in (folder / name, ROOT / "videos" / name, ROOT / name, Path(name)):
            if cand.exists():
                return cand.resolve()
        raise SystemExit(f"Video '{name}' not found. Put it in {folder} (or in videos/).")
    found = [f for f in folder.iterdir() if f.suffix.lower() in VIDEO_TYPES]
    if len(found) == 1:
        return found[0].resolve()
    if not found:
        raise SystemExit(f"No video for track '{folder.name}'. Put the NASA video in {folder}.")
    raise SystemExit(f"Several videos in {folder}: set `video = \"...\"` in track.toml to pick one.")


def load_track(name_or_path):
    """Read tracks/<name>/track.toml -> settings dict for the engine (paths made absolute)."""
    folder = track_dir(name_or_path)
    path = folder / "track.toml"
    with open(path, "rb") as fh:
        try:
            raw = tomllib.load(fh)
        except tomllib.TOMLDecodeError as e:
            raise SystemExit(f"There's a typo in {path}: {e}")

    for k in raw:
        if k not in KNOWN:
            print(f"! {folder.name}/track.toml: unknown setting '{k}' ignored")
    cfg = {k: raw.get(k, v) for k, v in KNOWN.items()}
    kind = cfg["kind"]
    if kind not in NEEDED:
        raise SystemExit(f"{folder.name}/track.toml: kind must be \"field\" or \"categories\", not \"{kind}\"")
    missing = [k for k in ["title", "start_time", "hours_per_frame"] + NEEDED[kind] if cfg.get(k) is None]
    if missing:
        raise SystemExit(f"{folder.name}/track.toml is missing: {', '.join(missing)}")

    cfg["id"] = folder.name
    cfg["folder"] = folder
    cfg["ignore"] = [tuple(box) for box in cfg["ignore"]]
    if cfg["colorbar"]:
        cb = dict(cfg["colorbar"])
        img = Path(cb.get("image", "colorbar.png"))
        cb["image"] = str(img if img.is_absolute() else (folder / img))
        cfg["colorbar"] = cb
    sounds = folder / "sounds.toml"
    cfg["sounds"] = str(sounds)
    return cfg


def all_tracks():
    return {name: load_track(name) for name in all_track_names()}
