"""Writing track.toml and sounds.toml (used by the studio when you press Save).

Python can read TOML but not write it, so this is a small writer for the settings
we use. It keeps the files readable: a fixed order, short comments, blank lines.
"""

import math


def value(v):
    """One TOML value."""
    if v is None:
        return '"none"'
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return '"none"'
        v = round(v, 6)
        return str(int(v)) if v.is_integer() and abs(v) < 1e15 else repr(v)   # 12, not 12.0
    if isinstance(v, str):
        if "\n" in v:
            return '"""' + v.replace("\\", "\\\\").replace('"""', '\\"\\"\\"') + '"""'
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{k} = {value(x)}" for k, x in v.items()) + " }"
    raise TypeError(f"can't write {type(v).__name__} to TOML")


def line(key, v, comment=""):
    s = f"{key} = {value(v)}"
    return f"{s:<34} # {comment}" if comment else s


# ---------------------------------------------------------------- track.toml

TRACK_LAYOUT = [
    ("Shown on the website (and read by screen readers)", [
        ("title", ""), ("source", ""), ("description", ""), ("listening_guide", ""),
    ]),
    ("The video", [
        ("kind", '"field" = a value everywhere on the map'),
        ("video", "empty = the video file in this folder"),
        ("start_time", "first frame, in UTC"),
        ("hours_per_frame", ""),
        ("slow_down", "play this many times slower"),
        ("smooth_video", "blend frames so the slowed video isn't choppy"),
        ("ignore", "boxes to ignore: [x0, y0, x1, y1] in video pixels"),
    ]),
    ("Words for the daily captions", [
        ("caption_high", ""), ("caption_low", ""), ("caption_share", ""), ("caption_share_name", ""),
    ]),
    ("What the colors mean", [
        ("units", ""),
        ("color_space", '"rgb" or "lab" (compare colors the way they look)'),
        ("max_color_distance", "how close a pixel must be to a color bar color"),
        ("unmatched_value", "colors not on the bar count as this value (leave out = ignore them)"),
        ("hot_threshold", "high threshold (for the graph)"),
        ("cold_threshold", "the captions give the share of the N. Hemisphere below this"),
        ("very_cold_threshold", ""),
        ("colorbar", "the color bar image in this folder and what its ends mean"),
        ("map", "flat world map filling the whole frame"),
    ]),
]


def track_toml(t, title_comment=None):
    out = ["# " + "=" * 77,
           f"#  Track: {t.get('title', '')}",
           f"#  Build it:  py sonify.py {t.get('id', '<name>')}     (or use the studio: py studio.py)",
           "#  The sound is set in sounds.toml (same folder).",
           "# " + "=" * 77]
    written = set()
    for heading, keys in TRACK_LAYOUT:
        block = []
        for k, c in keys:
            if k not in t or t[k] is None or k in written:
                continue
            v = t[k]
            if k in ("listening_guide", "ignore") and not v:
                block.append(line(k, [], c))
            elif k == "listening_guide":
                block.append("listening_guide = [")
                block += [f"  {value(x)}," for x in v]
                block.append("]")
            elif k == "ignore":
                block.append(f"ignore = [{'  # ' + c if c else ''}")
                block += [f"  {value(list(b))}," for b in v]
                block.append("]")
            else:
                block.append(line(k, v, c))
            written.add(k)
        if block:
            out += ["", f"# --- {heading} " + "-" * max(3, 72 - len(heading)), *block]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- sounds.toml

SOUND_ORDER = ["name", "kind", "enabled", "volume",
               "instrument", "texture", "harmonics", "detune_cents", "decay", "brightness", "attack",
               "cutoff", "low", "high",
               "sample", "root", "pitched", "length", "crossfade",
               "measure", "range", "hemisphere", "pitch_range", "bands",
               "lowest_note", "highest_note", "note", "add_fifth", "units_per_step",
               "per_second_min", "per_second_max", "pitch_jitter", "quiet", "loud", "stereo_width",
               "level_min", "curve", "glide", "hysteresis", "smoothing", "pans", "band_volumes"]

SOUND_HELP = {
    "kind": "voices / hits / background / chime",
    "enabled": "false = muted",
    "instrument": "built-in synth (ignored when `sample` is set)",
    "sample": "your own WAV file (\"\" = use the built-in instrument)",
    "root": "the note the sample plays",
    "pitched": "false = play the sample as recorded",
    "length": "seconds of the sample to use (0 = all)",
    "range": "values this sound follows: [low, high], \"none\" = no limit",
    "pitch_range": "values mapped to lowest..highest note (empty = the range)",
    "measure": '"mean" = global average, "area" = share inside range',
    "hemisphere": '"all", "north" or "south"',
    "units_per_step": "this much change = one scale step",
    "per_second_min": "notes per second at the least...",
    "per_second_max": "...and at the most",
    "level_min": "volume at the least (0..1)",
    "curve": ">1 = only loud at the most",
    "bands": "which latitude bands (0 = Arctic .. 4 = Antarctic); empty = all",
}


def _clean(v):
    if isinstance(v, list):
        return [_clean(x) for x in v]
    return v


def sounds_toml(snd, track_title=""):
    out = ["# " + "=" * 77,
           f"#  Sound settings for \"{track_title}\"",
           "#  Each [[sound]] block is one sound; kinds: voices, hits, background, chime.",
           "#  Any setting you leave out uses its default (SOUND_DEFAULTS in jukebox/config.py).",
           "# " + "=" * 77, ""]
    for section in ("music", "mix"):
        out.append(f"[{section}]")
        for k, v in snd.get(section, {}).items():
            out.append(line(k, v))
        out.append("")
    for s in snd.get("sounds", []):
        out += ["", "[[sound]]"]
        keys = [k for k in SOUND_ORDER if k in s] + [k for k in s if k not in SOUND_ORDER]
        for k in keys:
            v = s[k]
            if k in ("range", "pitch_range", "bands") and not v:
                continue
            if k.startswith("_"):
                continue
            out.append(line(k, _clean(v), SOUND_HELP.get(k, "")))
    return "\n".join(out) + "\n"
