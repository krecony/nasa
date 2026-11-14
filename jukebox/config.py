"""Loading the sound settings file (sounds/*.toml).

The DEFAULTS below are the fallback for every setting, so you can delete lines
from the .toml file and they'll go back to these values. Unknown settings
(usually typos) are reported so they don't silently do nothing.
"""

import copy
from pathlib import Path

try:
    import tomllib                      # Python 3.11+
except ImportError:                     # pragma: no cover
    try:
        import tomli as tomllib         # older Python: py -m pip install tomli
    except ImportError:
        raise SystemExit("Reading sounds/*.toml needs Python 3.11+ (or: py -m pip install tomli)")

RAIN_DEFAULTS = {
    "music": {
        "key": "D",
        "scale": "major_pentatonic",
        "day_chords": [[0, 7, 16], [-3, 4, 12], [-5, 2, 11], [-3, 7, 14]],
    },
    "mix": {"reverb_seconds": 2.4, "reverb_wet": 0.28, "peak": 0.89},
    "drops": {
        "enabled": True, "volume": 0.19,
        "instrument": "marimba", "decay": 0.32, "brightness": 0.5, "attack": 0.003,
        "sample": "", "root": "C4", "pitched": True, "length": 0.0,
        "per_second_min": 7.0, "per_second_max": 28.0,
        "lowest_note": "D3", "highest_note": "D6", "south_lat": -60.0, "north_lat": 60.0,
        "pitch_jitter": 1, "quiet": 0.4, "loud": 1.0, "stereo_width": 0.95,
    },
    "pad": {
        "enabled": True, "volume": 0.26,
        "instrument": "pad", "harmonics": [1.0, 0.45, 0.25, 0.12], "detune_cents": 7.0,
        "sample": "", "root": "C4", "crossfade": 0.3,
        "octave": 3, "bass": True, "level_min": 0.3, "level_max": 1.0, "glide": 0.25,
        "pans": [-0.5, -0.15, 0.15, 0.5],
    },
    "thunder": {
        "enabled": True, "volume": 0.45,
        "texture": "rumble", "cutoff": 110.0, "low": 200.0, "high": 2000.0,
        "sample": "", "curve": 1.5,
        "boom": "boom", "boom_sample": "", "boom_volume": 1.3, "boom_decay": 0.7,
        "boom_threshold": 0.8, "boom_cooldown": 1.8,
    },
    "snow": {
        "enabled": True, "volume": 0.06,
        "instrument": "bell", "decay": 1.2, "brightness": 0.5, "attack": 0.005,
        "sample": "", "root": "C4", "pitched": True, "length": 0.0,
        "per_second_min": 0.8, "per_second_max": 5.3, "octaves_up": [2, 3],
    },
    "chime": {
        "enabled": True, "volume": 0.12,
        "instrument": "bell", "decay": 2.2, "brightness": 0.5, "attack": 0.005,
        "sample": "", "root": "C4", "pitched": True, "length": 0.0,
        "note": "D5", "add_fifth": True,
    },
}

# Defaults for "field" tracks (a value everywhere, e.g. temperature)
FIELD_DEFAULTS = {
    "music": {"key": "E", "scale": "minor_pentatonic"},
    "mix": {"reverb_seconds": 2.8, "reverb_wet": 0.3, "peak": 0.89},
    "choir": {
        "enabled": True, "volume": 0.14,
        "instrument": "pad", "harmonics": [1.0, 0.35, 0.15, 0.06], "detune_cents": 6.0,
        "sample": "", "root": "C4", "crossfade": 0.3,
        "lowest_note": "E2", "highest_note": "E5", "coldest": -40.0, "warmest": 35.0,
        "degrees_per_step": 1.0, "glide": 0.4, "hysteresis": 0.3, "smoothing": 5,
        "pans": [-0.8, -0.4, 0.0, 0.4, 0.8], "band_volumes": [0.8, 1.0, 0.9, 1.0, 0.8],
    },
    "heat": {
        "enabled": True, "volume": 0.42,
        "instrument": "pluck", "decay": 0.5, "brightness": 0.6, "attack": 0.0,
        "sample": "", "root": "C4", "pitched": True, "length": 0.0,
        "per_second_min": 2.0, "per_second_max": 22.0,
        "lowest_note": "E4", "highest_note": "E6", "hot_from": 30.0, "hot_to": 42.0,
        "pitch_jitter": 1, "quiet": 0.4, "loud": 1.0, "stereo_width": 0.95,
    },
    "frost": {
        "enabled": True, "volume": 0.35,
        "texture": "noise", "cutoff": 110.0, "low": 300.0, "high": 2500.0, "sample": "",
        "measure": "freeze_nh", "level_min": 0.15, "curve": 1.0,
    },
    "chime": {
        "enabled": True, "volume": 0.1,
        "instrument": "bell", "decay": 2.2, "brightness": 0.5, "attack": 0.005,
        "sample": "", "root": "C4", "pitched": True, "length": 0.0,
        "note": "E5", "add_fifth": True,
    },
}

DEFAULTS = {"categories": RAIN_DEFAULTS, "field": FIELD_DEFAULTS}
LAYERS_BY_KIND = {"categories": ["pad", "drops", "thunder", "snow", "chime"],
                  "field": ["choir", "heat", "frost", "chime"]}
LAYERS = LAYERS_BY_KIND["categories"]


def load_sounds(path, kind="categories"):
    path = Path(path)
    if not path.exists():
        raise SystemExit(f"Sound settings file not found: {path}")
    with open(path, "rb") as fh:
        try:
            user = tomllib.load(fh)
        except tomllib.TOMLDecodeError as e:
            raise SystemExit(f"There's a typo in {path.name}: {e}")

    cfg = copy.deepcopy(DEFAULTS[kind])
    for section, values in user.items():
        if section not in cfg:
            print(f"! {path.name}: unknown section [{section}] ignored (sections: {', '.join(cfg)})")
            continue
        for k, v in values.items():
            if k not in cfg[section]:
                print(f"! {path.name}: unknown setting '{k}' in [{section}] ignored")
                continue
            cfg[section][k] = v
    cfg["_dir"] = Path(__file__).resolve().parent.parent   # sample paths: relative to the project folder
    return cfg
