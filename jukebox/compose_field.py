"""The "score" for field tracks (a value everywhere, e.g. temperature).

  What you see                                   What you hear              Settings
  ---------------------------------------------  -------------------------  ---------
  Average temperature of 5 latitude bands        5 sustained voices         [choir]
    (Arctic, N mid-lat, tropics, S mid-lat,        warmer = higher note
     Antarctic)
  Places hotter than 30 C                        Plucks                     [heat]
    ...how much of the globe                       ...plucks per second
    ...where, west -> east                         ...left -> right
    ...how hot                                     ...pitch and loudness
  Northern Hemisphere below freezing (0 C)       Wind texture               [frost]
  A new day (00:00 UTC)                          Chime                      [chime]

All numbers are in the sound settings file (sounds/gmao_t2m.toml).
"""

import numpy as np

from . import synth
from .compose import normalize, per_sample, glide, notes_in_range, stereo
from .config import LAYERS_BY_KIND
from .features import smooth
from .field import N_BANDS
from .instruments import NoteInstrument, note_to_midi, texture, load_sample, repitch, loop_to_length
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


def render(feats, preset, tl, snd, seed=0, only=None):
    music, base_dir = snd["music"], snd["_dir"]
    rng = np.random.default_rng(seed)
    nF, dt, ft = tl["n_frames"], tl["seconds_per_frame"], tl["frame_time"]
    data_end = tl["data_end"]
    tail = 2.5
    n = int((tl["duration"] + tail) * SR)
    valid = np.arange(nF) < data_end
    active = [l for l in LAYERS_BY_KIND["field"] if snd[l]["enabled"] and (not only or l in only)]
    band_pos = (np.arange(N_BANDS) + 0.5) / N_BANDS * 2 - 1

    t = np.arange(n) / SR
    end_t = data_end * dt
    fade = np.clip(1 - (t - end_t) / (tail * 0.7), 0, 1) * np.clip(t / 0.5, 0, 1)
    stems = {}

    # --- choir: one voice per latitude band -----------------------------------------
    if "choir" in active:
        c = snd["choir"]
        scale = notes_in_range(music["key"], music["scale"], c["lowest_note"], c["highest_note"])
        lat = smooth(np.array([f["lat_mean"] for f in feats]), max(int(c["smoothing"]), 1))
        buf = np.zeros((n, 2))
        for b in range(lat.shape[1]):
            # starting note from the band's average temperature, then every
            # `degrees_per_step` of change moves the voice one scale step
            avg = lat[valid, b].mean()
            base = np.interp(avg, [c["coldest"], c["warmest"]], [0, len(scale) - 1])
            cont = base + (lat[:, b] - avg) / c["degrees_per_step"]
            steps = quantize(cont, c["hysteresis"])
            midi = np.array(scale)[np.clip(steps, 0, len(scale) - 1)]
            vol = c["band_volumes"][b % len(c["band_volumes"])] if c["band_volumes"] else 1.0
            tone = sustained_voice(midi, dt, n, c, base_dir) * vol * fade
            buf += stereo(tone, c["pans"][b % len(c["pans"])] if c["pans"] else 0.0)
        stems["choir"] = buf

    # --- heat: plucks where it's hot -----------------------------------------------------
    if "heat" in active:
        c = snd["heat"]
        inst = NoteInstrument(c, base_dir, "heat")
        scale = notes_in_range(music["key"], music["scale"], c["lowest_note"], c["highest_note"])
        hot = normalize(smooth(np.array([f["hot_area"] for f in feats]), 3), valid)
        band_hot = np.array([f["band_hot"] for f in feats])
        band_val = np.array([f["band_hot_val"] for f in feats])
        buf = np.zeros((n, 2))
        for i in range(data_end):
            w = band_hot[i]
            if w.sum() <= 0:
                continue
            per_s = c["per_second_min"] + (c["per_second_max"] - c["per_second_min"]) * hot[i]
            for b in rng.choice(N_BANDS, rng.poisson(per_s * dt), p=w / w.sum()):
                heat01 = np.clip((band_val[i, b] - c["hot_from"]) / (c["hot_to"] - c["hot_from"]), 0, 1)
                j = c["pitch_jitter"]
                k = int(np.clip(round(heat01 * (len(scale) - 1)) + rng.integers(-j, j + 1), 0, len(scale) - 1))
                loud = c["quiet"] + (c["loud"] - c["quiet"]) * heat01
                synth.add_mono(buf, inst(synth.midi_to_hz(scale[k])), ft[i] + rng.uniform(0, dt),
                               pan=band_pos[b] * c["stereo_width"], gain=loud * rng.uniform(0.7, 1.0))
        stems["heat"] = buf

    # --- frost: wind that grows with the frozen area ------------------------------------
    if "frost" in active:
        c = snd["frost"]
        measure = np.array([f[c["measure"]] for f in feats])
        level = c["level_min"] + (1 - c["level_min"]) * normalize(smooth(measure, 9), valid) ** c["curve"]
        env = glide(per_sample(level, ft, n), 0.3) * fade
        buf = np.zeros((n, 2))
        if c["sample"]:
            tex = texture(c, n, base_dir, seed=1)
            buf += np.stack([tex, np.roll(tex, int(0.37 * SR))], axis=1) * env[:, None]
        else:
            buf[:, 0] = texture(c, n, base_dir, seed=1) * env
            buf[:, 1] = texture(c, n, base_dir, seed=2) * env
        stems["frost"] = buf

    # --- chime at each new day ------------------------------------------------------------
    if "chime" in active:
        c = snd["chime"]
        inst = NoteInstrument(c, base_dir, "chime")
        m = note_to_midi(c["note"])
        sound = inst(synth.midi_to_hz(m)).copy()
        if c["add_fifth"]:
            fifth = inst(synth.midi_to_hz(m + 7))
            k = min(len(sound), len(fifth))
            sound[:k] += 0.5 * fifth[:k]
        buf = np.zeros((n, 2))
        for d in tl["day_starts"]:
            if tl["dates"][d].hour == 0:
                synth.add_mono(buf, sound, ft[d], pan=0.0)
        stems["chime"] = buf

    if not stems:
        raise SystemExit("All layers are muted - nothing to render.")
    mx = snd["mix"]
    stems = {k: synth.reverb(s * snd[k]["volume"], seconds=mx["reverb_seconds"], wet=mx["reverb_wet"])
             for k, s in stems.items()}
    mix = sum(stems.values())
    scale_to_peak = mx["peak"] / (np.abs(np.tanh(mix * 1.2)).max() + 1e-9)
    audio = (np.tanh(mix * 1.2) * scale_to_peak).astype(np.float32)
    stems = {k: (s * 1.2 * scale_to_peak).astype(np.float32) for k, s in stems.items()}
    return audio, stems
