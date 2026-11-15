"""Loading the sound settings file (tracks/<name>/sounds.toml).

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
        raise SystemExit("Reading the .toml settings files needs Python 3.11+ (or: py -m pip install tomli)")

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

# ---- "field" tracks: a free list of sounds ([[sound]] blocks in sounds.toml) ----------------
# Defaults for each kind of sound. `range = [low, high]` is in the track's units
# (e.g. degrees C or m/s); leave one side out ([20] or [nan, 5]... see below) for "no limit".
_NOTE_INSTRUMENT = {"instrument": "pluck", "decay": 0.5, "brightness": 0.6, "attack": 0.0,
                    "sample": "", "root": "C4", "pitched": True, "length": 0.0}
SOUND_DEFAULTS = {
    "voices": {
        "name": "", "enabled": True, "volume": 0.14,
        "instrument": "pad", "harmonics": [1.0, 0.35, 0.15, 0.06], "detune_cents": 6.0,
        "sample": "", "root": "C4", "crossfade": 0.3,
        "range": [], "lowest_note": "E2", "highest_note": "E5", "units_per_step": 1.0,
        "glide": 0.4, "hysteresis": 0.3, "smoothing": 5, "bands": [],
        "pans": [-0.8, -0.4, 0.0, 0.4, 0.8], "band_volumes": [0.8, 1.0, 0.9, 1.0, 0.8],
    },
    "hits": dict(_NOTE_INSTRUMENT, **{
        "name": "", "enabled": True, "volume": 0.42,
        "range": [], "pitch_range": [], "per_second_min": 2.0, "per_second_max": 22.0,
        "lowest_note": "E4", "highest_note": "E6", "pitch_jitter": 1,
        "quiet": 0.4, "loud": 1.0, "stereo_width": 0.95, "smoothing": 3,
    }),
    "background": {
        "name": "", "enabled": True, "volume": 0.35,
        "texture": "noise", "cutoff": 110.0, "low": 300.0, "high": 2500.0, "sample": "",
        "measure": "area", "range": [], "hemisphere": "all",
        "level_min": 0.15, "curve": 1.0, "smoothing": 9,
    },
    "chime": dict(_NOTE_INSTRUMENT, **{
        "name": "", "enabled": True, "volume": 0.1,
        "instrument": "bell", "decay": 2.2, "brightness": 0.5, "attack": 0.005,
        "note": "E5", "add_fifth": True,
    }),
}
FIELD_GLOBAL = {"music": dict(FIELD_DEFAULTS["music"]), "mix": dict(FIELD_DEFAULTS["mix"])}
ALIASES = {"degrees_per_step": "units_per_step"}


def _clean_range(r):
    """[20] -> [20, None]; [] -> []; values given as "" or "none" -> None (no limit)."""
    if r is None:
        return []
    r = list(r)
    if len(r) == 1:
        r.append(None)
    return [None if (v is None or (isinstance(v, str) and v.strip().lower() in ("", "none", "inf", "-inf"))) else v
            for v in r[:2]]


def _field_sounds(user, path, preset):
    cfg = copy.deepcopy(FIELD_GLOBAL)
    for section in ("music", "mix"):
        for k, v in user.get(section, {}).items():
            if k not in cfg[section]:
                print(f"! {path.name}: unknown setting '{k}' in [{section}] ignored")
                continue
            cfg[section][k] = v

    if "sound" in user:
        raw = user["sound"]
        for section in user:
            if section not in ("music", "mix", "sound"):
                print(f"! {path.name}: unknown section [{section}] ignored")
    else:
        raw = _convert_old(user, path, preset)

    sounds, names = [], set()
    for i, s in enumerate(raw, 1):
        kind = s.get("kind")
        if kind not in SOUND_DEFAULTS:
            raise SystemExit(f"{path.name}: sound #{i} needs kind = one of {', '.join(SOUND_DEFAULTS)} (got {kind!r})")
        d = copy.deepcopy(SOUND_DEFAULTS[kind])
        for k, v in s.items():
            k = ALIASES.get(k, k)
            if k == "kind":
                continue
            if k not in d:
                print(f"! {path.name}: unknown setting '{k}' in sound #{i} ({kind}) ignored")
                continue
            d[k] = v
        d["kind"] = kind
        d["range"], d["pitch_range"] = _clean_range(d.get("range")), _clean_range(d.get("pitch_range"))
        base = d["name"] or kind
        name, k = base, 2
        while name in names:
            name, k = f"{base}{k}", k + 1
        d["name"] = name
        names.add(name)
        sounds.append(d)
    cfg["sounds"] = sounds
    return cfg


def _convert_old(user, path, preset):
    """Old-style file ([choir], [heat], [frost], [chime]) -> list of sounds, same sound as before."""
    old = copy.deepcopy(FIELD_DEFAULTS)
    for section, values in user.items():
        if section in ("music", "mix"):
            continue
        if section not in old:
            print(f"! {path.name}: unknown section [{section}] ignored")
            continue
        for k, v in values.items():
            if k in old[section]:
                old[section][k] = v
            else:
                print(f"! {path.name}: unknown setting '{k}' in [{section}] ignored")
    p = preset or {}
    hot, cold, very = p.get("hot_threshold", 30), p.get("cold_threshold", 0), p.get("very_cold_threshold", -20)
    c, h, f, ch = old["choir"], old["heat"], old["frost"], old["chime"]
    measure = {"mean": ("mean", [], "all"), "freeze_nh": ("area", [None, cold], "north"),
               "freeze_area": ("area", [None, cold], "all"), "cold_area": ("area", [None, very], "all"),
               "hot_area": ("area", [hot, None], "all")}.get(f["measure"])
    if measure is None:
        raise SystemExit(f"{path.name}: [frost] measure {f['measure']!r} unknown")
    keep = lambda d, keys: {k: d[k] for k in keys if k in d}
    return [
        dict(keep(c, SOUND_DEFAULTS["voices"]), kind="voices", name="choir", range=[c["coldest"], c["warmest"]],
             units_per_step=c["degrees_per_step"]),
        dict(keep(h, SOUND_DEFAULTS["hits"]), kind="hits", name="heat", range=[hot, None],
             pitch_range=[h["hot_from"], h["hot_to"]]),
        dict(keep(f, SOUND_DEFAULTS["background"]), kind="background", name="frost",
             measure=measure[0], range=measure[1], hemisphere=measure[2]),
        dict(keep(ch, SOUND_DEFAULTS["chime"]), kind="chime", name="chime"),
    ]


def load_sounds(path, kind="categories", track_folder=None, preset=None):
    path = Path(path)
    if not path.exists():
        raise SystemExit(f"Sound settings file not found: {path}")
    with open(path, "rb") as fh:
        try:
            user = tomllib.load(fh)
        except tomllib.TOMLDecodeError as e:
            raise SystemExit(f"There's a typo in {path.name}: {e}")

    if kind == "field":
        cfg = _field_sounds(user, path, preset)
    else:
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
    # sample paths are looked up in the track's folder first, then in the project folder
    project = Path(__file__).resolve().parent.parent
    cfg["_dir"] = [Path(track_folder), project] if track_folder else [project]
    return cfg
