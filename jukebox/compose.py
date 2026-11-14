"""Step 4: the "score" - how features become music.

All numbers you might want to change live in the sound settings file
(sounds/imerg.toml). This file only contains the logic:

  What you see                         What you hear              Settings
  ---------------------------------    -------------------------  ----------
  Rain anywhere on Earth               Raindrops                  [drops]
    ...how much rain in total            ...drops per second
    ...where it is, west -> east         ...left -> right
    ...how far north it is               ...pitch (north = higher)
    ...how intense it is                 ...how loud each drop is
  Heavy rain (>= heavy_threshold)      Thunder texture + booms     [thunder]
  Snow                                 Bells                       [snow]
  Global rain coverage (daily pulse)   Chord pad swelling          [pad]
  A new day (00:00 UTC)                Chime + chord change        [chime], [music]

Most global numbers only change a little (rain covers 5.5-6.6% of the globe),
so for the music each feature is stretched to 0..1 over this clip
(normalize()). The spoken descriptions use the real values.
"""

import numpy as np
from scipy import signal

from . import synth
from .config import LAYERS
from .features import series, smooth, N_BANDS
from .instruments import NoteInstrument, note_to_midi, texture, boom, load_sample, repitch, loop_to_length
from .synth import SAMPLE_RATE as SR


def normalize(x, valid, lo_pct=5, hi_pct=95):
    lo, hi = np.percentile(x[valid], [lo_pct, hi_pct])
    return np.clip((x - lo) / (hi - lo + 1e-12), 0, 1)


def intensity01(rate_mm_h):
    """Rain rate on a log scale: 0.2 mm/h -> 0, 20 mm/h -> 1."""
    r = np.maximum(rate_mm_h, 1e-6)
    return np.clip(np.log10(r / 0.2) / np.log10(100), 0, 1)


def per_sample(frame_values, frame_time, n):
    """Stretch one-value-per-frame to one-value-per-sample (linear)."""
    return np.interp(np.arange(n) / SR, frame_time, frame_values)


def glide(x, seconds):
    """One-pole smoothing per sample: makes steps (chord changes) glide."""
    a = np.exp(-1.0 / (max(seconds, 1e-3) * SR))
    y, _ = signal.lfilter([1 - a], [1, -a], x, zi=[x[0] * a])
    return y


def notes_in_range(key, scale, low, high):
    """All notes of the scale between two note names, e.g. ('D','major_pentatonic','D3','D6')."""
    if scale not in synth.SCALES:
        raise SystemExit(f"[music] unknown scale '{scale}'. Choose: {', '.join(synth.SCALES)}")
    steps = set(synth.SCALES[scale])
    k = synth.NOTE_NAMES.index(key)
    lo, hi = note_to_midi(low), note_to_midi(high)
    notes = [m for m in range(lo, hi + 1) if (m - k) % 12 in steps]
    if not notes:
        raise SystemExit(f"No notes of {key} {scale} between {low} and {high}")
    return notes


def stereo(mono, pan):
    gl, gr = synth.pan_gains(pan)
    return np.stack([mono * gl, mono * gr], axis=1)


# --- layers -------------------------------------------------------------------------

def render_pad(c, music, chords, day, ft, tl, level, n, base_dir):
    out = np.zeros((n, 2))
    root = synth.note_midi(music["key"], c["octave"])
    voices = [([root + ch[0] - 12] if c["bass"] else []) + [root + d for d in ch] for ch in chords]
    pans = c["pans"] or [0.0]
    level = glide(level, 0.3)

    if not c["sample"]:
        for v in range(len(voices[0])):
            midi = np.array([voices[day[i] % len(voices)][v] for i in range(tl["n_frames"])], float)
            f = synth.midi_to_hz(glide(np.repeat(midi, int(np.ceil(n / len(midi))))[:n], c["glide"]))
            tone = synth.pad_voice(f, level, harmonics=tuple(c["harmonics"]), detune_cents=c["detune_cents"])
            out += stereo(tone, pans[v % len(pans)])
        return out

    # WAV pad: each day, loop the sample at every chord note, crossfading into the next day
    smp = load_sample(c["sample"], base_dir)
    root_hz = float(synth.midi_to_hz(note_to_midi(c["root"])))
    xf = int(max(c["glide"], 0.2) * SR)
    starts = [int(ft[d] * SR) for d in tl["day_starts"]] + [n]
    for k, (s0, s1) in enumerate(zip(starts[:-1], starts[1:])):
        seg_len = min(s1 - s0 + xf, n - s0)
        env = np.ones(seg_len)
        env[:min(xf, seg_len)] = np.linspace(0, 1, min(xf, seg_len))
        if s1 < n:
            env[-min(xf, seg_len):] = np.linspace(1, 0, min(xf, seg_len))
        for v, midi in enumerate(voices[k % len(voices)]):
            x = repitch(smp, float(synth.midi_to_hz(midi)) / root_hz)
            tone = loop_to_length(x, seg_len, c["crossfade"]) * env * 0.35
            out[s0:s0 + seg_len] += stereo(tone, pans[v % len(pans)])
    return out * level[:, None]


def render(feats, preset, tl, snd, seed=0, only=None):
    """Render the soundtrack.

    snd:  sound settings (from config.load_sounds)
    only: list of layer names to keep (others muted), for testing
    Returns (stereo float32 mix, dict of stereo stems after reverb).
    """
    music, base_dir = snd["music"], snd["_dir"]
    rng = np.random.default_rng(seed)
    nF, data_end, dt = tl["n_frames"], tl["data_end"], tl["seconds_per_frame"]
    ft = tl["frame_time"]
    tail = 2.0
    n = int((tl["duration"] + tail) * SR)
    valid = np.arange(nF) < data_end
    active = [l for l in LAYERS if snd[l]["enabled"] and (not only or l in only)]

    # --- features, smoothed and normalised ---------------------------------
    liq_cover = normalize(smooth(series(feats, "liquid", "area"), 9), valid)
    heavy = normalize(smooth(series(feats, "liquid", "heavy"), 7), valid)
    snow_cover = normalize(smooth(series(feats, "frozen", "area"), 9), valid)
    band_area = series(feats, "liquid", "band_area")
    band_rate = series(feats, "liquid", "band_rate")
    band_lat = series(feats, "liquid", "band_lat")
    snow_band = series(feats, "frozen", "band_area")
    band_pos = (np.arange(N_BANDS) + 0.5) / N_BANDS * 2 - 1           # -1 west .. +1 east

    chords = music["day_chords"]
    day = tl["day_of_frame"]
    key_root = synth.note_midi(music["key"], 3)
    stems = {}

    # fade-out once the data ends (the video holds the last frame)
    end_t = data_end * dt
    fade = np.clip(1 - (np.arange(n) / SR - end_t) / (tl["duration"] - end_t + tail * 0.6), 0, 1)

    # --- 1. pad -----------------------------------------------------------------
    if "pad" in active:
        c = snd["pad"]
        level = per_sample(c["level_min"] + (c["level_max"] - c["level_min"]) * liq_cover, ft, n) * fade
        stems["pad"] = render_pad(c, music, chords, day, ft, tl, level, n, base_dir)

    # --- 2. raindrops --------------------------------------------------------------
    if "drops" in active:
        c = snd["drops"]
        inst = NoteInstrument(c, base_dir, "drops")
        scale = notes_in_range(music["key"], music["scale"], c["lowest_note"], c["highest_note"])
        buf = np.zeros((n, 2))
        for i in range(data_end):
            weights = band_area[i] * (1 + np.log1p(band_rate[i]))
            if weights.sum() <= 0:
                continue
            per_s = c["per_second_min"] + (c["per_second_max"] - c["per_second_min"]) * liq_cover[i]
            for b in rng.choice(N_BANDS, rng.poisson(per_s * dt), p=weights / weights.sum()):
                k = np.interp(band_lat[i, b], [c["south_lat"], c["north_lat"]], [0, len(scale) - 1])
                j = c["pitch_jitter"]
                k = int(np.clip(round(k) + rng.integers(-j, j + 1), 0, len(scale) - 1))
                loud = c["quiet"] + (c["loud"] - c["quiet"]) * intensity01(band_rate[i, b])
                synth.add_mono(buf, inst(synth.midi_to_hz(scale[k])), ft[i] + rng.uniform(0, dt),
                               pan=band_pos[b] * c["stereo_width"] + rng.uniform(-0.04, 0.04),
                               gain=loud * rng.uniform(0.7, 1.0))
        stems["drops"] = buf

    # --- 3. thunder -----------------------------------------------------------------
    if "thunder" in active:
        c = snd["thunder"]
        env = glide(per_sample(heavy ** c["curve"], ft, n), 0.2) * fade
        buf = np.zeros((n, 2))
        if c["sample"]:
            tex = texture(c, n, base_dir, seed=1)
            buf += np.stack([tex, np.roll(tex, int(0.37 * SR))], axis=1) * env[:, None]
        else:
            buf[:, 0] = texture(c, n, base_dir, seed=1) * env
            buf[:, 1] = texture(c, n, base_dir, seed=2) * env
        b_snd = boom(c, base_dir)
        last = -1e9
        for i in range(1, data_end):
            if heavy[i] > c["boom_threshold"] and heavy[i] > heavy[i - 1] and ft[i] - last > c["boom_cooldown"]:
                pan = np.clip(feats[i]["liquid"]["lon_c"] / 180, -0.7, 0.7)
                synth.add_mono(buf, b_snd, ft[i], pan=pan, gain=c["boom_volume"])
                last = ft[i]
        stems["thunder"] = buf

    # --- 4. snow -------------------------------------------------------------------------
    if "snow" in active:
        c = snd["snow"]
        inst = NoteInstrument(c, base_dir, "snow")
        octs = c["octaves_up"] or [2]
        buf = np.zeros((n, 2))
        for i in range(data_end):
            w = snow_band[i]
            if w.sum() <= 0:
                continue
            per_s = c["per_second_min"] + (c["per_second_max"] - c["per_second_min"]) * snow_cover[i]
            for b in rng.choice(N_BANDS, rng.poisson(per_s * dt), p=w / w.sum()):
                chord = chords[day[i] % len(chords)]
                midi = key_root + chord[rng.integers(len(chord))] + 12 * octs[rng.integers(len(octs))]
                synth.add_mono(buf, inst(synth.midi_to_hz(midi)), ft[i] + rng.uniform(0, dt),
                               pan=band_pos[b] * 0.95, gain=rng.uniform(0.5, 1.0))
        stems["snow"] = buf

    # --- 5. day chime --------------------------------------------------------------------
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
            synth.add_mono(buf, sound, ft[d], pan=0.0)
        stems["chime"] = buf

    # --- mix ---------------------------------------------------------------------------
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
