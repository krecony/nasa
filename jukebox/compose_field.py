"""The "score" for field tracks (a value everywhere: temperature, wind, ...).

A track's sounds.toml is a list of sounds ([[sound]] blocks). Each sound has a kind:

  kind          what it follows                                  what you hear
  ------------  -----------------------------------------------  -------------------------------
  voices        the average value in 5 bands of latitude         5 held notes; higher value =
                (Arctic, N mid-lat, tropics, S mid-lat, Antarctic) higher note
  hits          places whose value is inside `range`             short notes: more area in the
                                                                 range = more notes; west->east =
                                                                 left->right; value = pitch/loudness
  background    the global average (measure = "mean"), or the    a looping texture whose volume
                share of the globe inside `range` ("area")       follows it
  chime         the start of every day (UTC)                     one note/chord per day

All numbers live in tracks/<name>/sounds.toml; defaults are in config.py (SOUND_DEFAULTS).
"""

import numpy as np

from . import synth
from .compose import normalize, per_sample, glide, notes_in_range, stereo
from .features import smooth
from .field import N_BANDS
from .instruments import NoteInstrument, note_to_midi, texture, load_sample, repitch, loop_to_length
from .ranges import Range
from .synth import SAMPLE_RATE as SR


def quantize(cont, hysteresis):
    """Continuous note positions -> whole scale steps, ignoring small wobbles."""
    cur = int(round(cont[0]))
    out = np.empty(len(cont), int)
    for i, x in enumerate(cont):
        if abs(x - cur) > 0.5 + hysteresis:
            cur = int(round(x))
        out[i] = cur
    return out


def sustained_voice(midi_per_frame, dt, n, c, base_dir):
    """A held note that follows a melody (one MIDI note per frame)."""
    idx = np.minimum((np.arange(n) / SR / dt).astype(int), len(midi_per_frame) - 1)
    midi = midi_per_frame[idx].astype(float)
    if not c["sample"]:
        f = synth.midi_to_hz(glide(midi, c["glide"]))
        return synth.pad_voice(f, np.ones(n), harmonics=tuple(c["harmonics"]), detune_cents=c["detune_cents"])

    # WAV sample: loop it at each note, crossfading when the note changes
    smp = load_sample(c["sample"], base_dir)
    root_hz = float(synth.midi_to_hz(note_to_midi(c["root"])))
    xf = int(max(c["glide"], 0.15) * SR)
    change = np.flatnonzero(np.diff(midi)) + 1
    starts = np.concatenate([[0], change, [n]])
    out = np.zeros(n)
    for s0, s1 in zip(starts[:-1], starts[1:]):
        seg_len = min(s1 - s0 + xf, n - s0)
        x = loop_to_length(repitch(smp, float(synth.midi_to_hz(midi[s0])) / root_hz), seg_len, c["crossfade"])
        env = np.ones(seg_len)
        k = min(xf, seg_len)
        if s0 > 0:
            env[:k] = np.linspace(0, 1, k)
        if s1 < n:
            env[-k:] = np.linspace(1, 0, k)
        out[s0:s0 + seg_len] += x * env * 0.35
    return out


def _range(c, lo_default, hi_default):
    r = c.get("range") or [None, None]
    lo = r[0] if r[0] is not None else lo_default
    hi = r[1] if len(r) > 1 and r[1] is not None else hi_default
    return lo, hi


# --- one function per kind --------------------------------------------------------------

def voices(c, ctx):
    music, feats, dt, n = ctx["music"], ctx["feats"], ctx["dt"], ctx["n"]
    scale = notes_in_range(music["key"], music["scale"], c["lowest_note"], c["highest_note"])
    lat = smooth(np.array([f["lat_mean"] for f in feats]), max(int(c["smoothing"]), 1))
    low, high = _range(c, ctx["vmin"], ctx["vmax"])
    bands = c["bands"] if c["bands"] else range(lat.shape[1])
    buf = np.zeros((n, 2))
    for b in bands:
        # starting note from the band's average value, then every `units_per_step`
        # of change moves the voice one scale step
        avg = lat[ctx["valid"], b].mean()
        base = np.interp(avg, [low, high], [0, len(scale) - 1])
        steps = quantize(base + (lat[:, b] - avg) / c["units_per_step"], c["hysteresis"])
        midi = np.array(scale)[np.clip(steps, 0, len(scale) - 1)]
        vol = c["band_volumes"][b % len(c["band_volumes"])] if c["band_volumes"] else 1.0
        tone = sustained_voice(midi, dt, n, c, ctx["base_dir"]) * vol * ctx["fade"]
        buf += stereo(tone, c["pans"][b % len(c["pans"])] if c["pans"] else 0.0)
    return buf


def hits(c, ctx):
    music, dt, n, ft, rng = ctx["music"], ctx["dt"], ctx["n"], ctx["ft"], ctx["rng"]
    inst = NoteInstrument(c, ctx["base_dir"], c["name"])
    scale = notes_in_range(music["key"], music["scale"], c["lowest_note"], c["highest_note"])
    low, high = _range(c, ctx["vmin"], None)
    rg = Range(ctx["edges"], low, high, ctx["log"])
    amount = normalize(smooth(rg.area(ctx["hist"]), max(int(c["smoothing"]), 1)), ctx["valid"])
    share, mean = rg.per_strip(ctx["hist"])
    p_lo, p_hi = c["pitch_range"] if c.get("pitch_range") else (low, high if high is not None else ctx["vmax"])
    band_pos = (np.arange(N_BANDS) + 0.5) / N_BANDS * 2 - 1
    buf = np.zeros((n, 2))
    for i in range(ctx["data_end"]):
        w = share[i]
        if w.sum() <= 0:
            continue
        per_s = c["per_second_min"] + (c["per_second_max"] - c["per_second_min"]) * amount[i]
        for b in rng.choice(N_BANDS, rng.poisson(per_s * dt), p=w / w.sum()):
            x01 = np.clip((mean[i, b] - p_lo) / ((p_hi - p_lo) or 1), 0, 1)
            j = c["pitch_jitter"]
            k = int(np.clip(round(x01 * (len(scale) - 1)) + rng.integers(-j, j + 1), 0, len(scale) - 1))
            loud = c["quiet"] + (c["loud"] - c["quiet"]) * x01
            synth.add_mono(buf, inst(synth.midi_to_hz(scale[k])), ft[i] + rng.uniform(0, dt),
                           pan=band_pos[b] * c["stereo_width"], gain=loud * rng.uniform(0.7, 1.0))
    return buf


def background(c, ctx):
    n, feats = ctx["n"], ctx["feats"]
    if c["measure"] == "mean":
        measure = np.array([f["mean"] for f in feats])
    elif c["measure"] == "area":
        low, high = _range(c, None, None)
        measure = Range(ctx["edges"], low, high, ctx["log"]).area(ctx["hist"], c["hemisphere"])
    else:
        raise SystemExit(f"[{c['name']}] measure must be \"mean\" or \"area\", not \"{c['measure']}\"")
    level = c["level_min"] + (1 - c["level_min"]) * normalize(smooth(measure, max(int(c["smoothing"]), 1)), ctx["valid"]) ** c["curve"]
    env = glide(per_sample(level, ctx["ft"], n), 0.3) * ctx["fade"]
    buf = np.zeros((n, 2))
    if c["sample"]:
        tex = texture(c, n, ctx["base_dir"], seed=1)
        buf += np.stack([tex, np.roll(tex, int(0.37 * SR))], axis=1) * env[:, None]
    else:
        buf[:, 0] = texture(c, n, ctx["base_dir"], seed=1) * env
        buf[:, 1] = texture(c, n, ctx["base_dir"], seed=2) * env
    return buf


def chime(c, ctx):
    tl, ft, n = ctx["tl"], ctx["ft"], ctx["n"]
    inst = NoteInstrument(c, ctx["base_dir"], c["name"])
    m = note_to_midi(c["note"])
    sound = inst(synth.midi_to_hz(m)).copy()
    if c["add_fifth"]:
        fifth = inst(synth.midi_to_hz(m + 7))
        k = min(len(sound), len(fifth))
        sound[:k] += 0.5 * fifth[:k]
    buf = np.zeros((n, 2))
    for d in tl["day_starts"]:
        if d > 0 or tl["dates"][0].hour == 0:      # not on the first frame if that's mid-day
            synth.add_mono(buf, sound, ft[d], pan=0.0)
    return buf


KINDS = {"voices": voices, "hits": hits, "background": background, "chime": chime}


def render(feats, preset, tl, snd, seed=0, only=None):
    """Render the soundtrack. Returns (stereo float32 mix, dict of stereo stems by sound name)."""
    nF, dt, data_end = tl["n_frames"], tl["seconds_per_frame"], tl["data_end"]
    tail = 2.5
    n = int((tl["duration"] + tail) * SR)
    t = np.arange(n) / SR
    end_t = data_end * dt
    edges = np.asarray(feats[0]["hist_edges"])
    cb = preset.get("colorbar") or {}
    ctx = {
        "feats": feats, "tl": tl, "music": snd["music"], "base_dir": snd["_dir"],
        "rng": np.random.default_rng(seed), "n": n, "dt": dt, "ft": tl["frame_time"], "data_end": data_end,
        "valid": np.arange(nF) < data_end,
        "fade": np.clip(1 - (t - end_t) / (tail * 0.7), 0, 1) * np.clip(t / 0.5, 0, 1),
        "hist": np.stack([f["hist"] for f in feats]).astype(float), "edges": edges,
        "log": cb.get("scale") == "log", "vmin": float(edges[0]), "vmax": float(edges[-1]),
    }

    stems = {}
    for c in snd["sounds"]:
        if not c["enabled"] or (only and c["name"] not in only):
            continue
        stems[c["name"]] = KINDS[c["kind"]](c, ctx) * c["volume"]

    if not stems:
        raise SystemExit("All sounds are muted - nothing to render.")
    mx = snd["mix"]
    stems = {k: synth.reverb(s, seconds=mx["reverb_seconds"], wet=mx["reverb_wet"]) for k, s in stems.items()}
    mix = sum(stems.values())
    scale_to_peak = mx["peak"] / (np.abs(np.tanh(mix * 1.2)).max() + 1e-9)
    audio = (np.tanh(mix * 1.2) * scale_to_peak).astype(np.float32)
    stems = {k: (s * 1.2 * scale_to_peak).astype(np.float32) for k, s in stems.items()}
    return audio, stems
