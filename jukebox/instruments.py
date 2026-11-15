"""Instruments: built-in synths or your own WAV files.

Every note layer (drops, snow, chime) gets a function freq -> sound.
The pad plays sustained chords, thunder plays a continuous texture + booms.

Built-in note instruments:  marimba, bell, pluck, sine
Built-in pad:               pad
Built-in textures:          rumble (low), noise (band of noise, e.g. hiss/wind)
Built-in boom:              boom

Your own WAV files:
  - for notes: a single note recording; tell us which note it is (root = "C4")
    and we speed it up / slow it down to play every other note.
    pitched = false plays it as-is (good for drums / drips).
  - for the pad: a sustained note; it gets looped and pitched to the chord.
  - for the thunder texture: any recording (rain, thunder, wind); it gets looped
    and its volume follows the heavy rain.
"""

import re
from pathlib import Path

import numpy as np
from scipy import signal
from scipy.io import wavfile

from . import synth
from .synth import SAMPLE_RATE as SR

NOTE_INSTRUMENTS = ["marimba", "bell", "pluck", "sine"]
TEXTURES = ["rumble", "noise"]


# --- notes --------------------------------------------------------------------

def note_to_midi(name):
    """'C4' -> 60, 'F#3' -> 54, 'Bb2' -> 46"""
    m = re.fullmatch(r"\s*([A-Ga-g])([#b]?)(-?\d)\s*", str(name))
    if not m:
        raise SystemExit(f"Can't read the note name '{name}' (use e.g. C4, F#3, Bb2)")
    letter, acc, octave = m.groups()
    midi = 12 * (int(octave) + 1) + synth.NOTE_NAMES.index(letter.upper())
    return midi + (1 if acc == "#" else -1 if acc == "b" else 0)


# --- WAV samples -----------------------------------------------------------------

_sample_cache = {}


def load_sample(path, base_dir):
    """Read a WAV file as mono float at 44.1 kHz, peak 1.0."""
    p = Path(path)
    if not p.is_absolute():
        # look in the track's folder, then the project folder, then where the command was run from
        bases = list(base_dir) if isinstance(base_dir, (list, tuple)) else [base_dir]
        p = next((Path(b) / p for b in bases + [Path.cwd()] if (Path(b) / p).exists()), Path(bases[0]) / p)
    if p in _sample_cache:
        return _sample_cache[p]
    if not p.exists():
        raise SystemExit(f"Sample file not found: {p}")
    try:
        sr, x = wavfile.read(p)
    except ValueError as e:
        raise SystemExit(f"Can't read {p.name} ({e}). Export it as a normal 16-bit or 24-bit WAV.")
    if np.issubdtype(x.dtype, np.integer):
        x = x / float(np.iinfo(x.dtype).max)
    x = x.astype(float)
    if x.ndim == 2:
        x = x.mean(axis=1)                              # stereo -> mono
    if sr != SR:
        g = np.gcd(sr, SR)
        x = signal.resample_poly(x, SR // g, sr // g)
    nz = np.flatnonzero(np.abs(x) > 0.01 * np.abs(x).max())
    if len(nz) == 0:
        raise SystemExit(f"{p.name} is silent")
    x = x[max(nz[0] - 32, 0):]                         # trim silence at the start
    x = x / np.abs(x).max()
    _sample_cache[p] = x
    return x


def repitch(x, ratio):
    """Play a sample faster (ratio > 1, higher) or slower (ratio < 1, lower)."""
    n_out = int(len(x) / ratio)
    return np.interp(np.arange(n_out) * ratio, np.arange(len(x)), x)


def fade_out(x, seconds):
    n = min(int(seconds * SR), len(x))
    if n > 0:
        x = x.copy()
        x[-n:] *= np.linspace(1, 0, n)
    return x


def loop_to_length(x, n, crossfade=0.3):
    """Repeat a sample until it is n samples long, with smooth crossfades."""
    cf = int(min(crossfade * SR, len(x) // 3))
    if len(x) >= n:
        return x[:n]
    out = np.zeros(n)
    step = len(x) - cf
    ramp = np.linspace(0, 1, cf) if cf > 0 else None
    pos = 0
    while pos < n:
        seg = x.copy()
        if cf > 0 and pos > 0:
            seg[:cf] *= ramp
        if cf > 0:
            seg[-cf:] *= ramp[::-1]
        end = min(pos + len(seg), n)
        out[pos:end] += seg[: end - pos]
        pos += step
    return out


# --- built-in note synths ------------------------------------------------------------

def _env(n, attack, decay):
    t = np.arange(n) / SR
    return np.minimum(t / max(attack, 1e-4), 1) * np.exp(-t / decay), t


def marimba(freq, decay=0.3, brightness=0.5, attack=0.003):
    """Wooden pluck: sine + a high inharmonic overtone that dies fast."""
    n = int(SR * decay * 5)
    env, t = _env(n, attack, decay)
    click = 0.7 * brightness * np.sin(2 * np.pi * freq * 3.93 * t) * np.exp(-t / (decay * 0.12))
    return np.sin(2 * np.pi * freq * t) * env + click * np.minimum(t / max(attack, 1e-4), 1)


def bell(freq, decay=1.2, brightness=0.5, attack=0.005):
    """Glassy bell: inharmonic partials; brightness scales the upper ones."""
    n = int(SR * decay * 4)
    t = np.arange(n) / SR
    out = np.zeros(n)
    for ratio, amp, d in [(1.0, 1.0, 1.0), (2.76, 0.4, 0.5), (5.40, 0.2, 0.3), (8.93, 0.08, 0.2)]:
        a = amp if ratio == 1.0 else amp * 2 * brightness
        out += a * np.sin(2 * np.pi * freq * ratio * t) * np.exp(-t / (decay * d))
    return out * np.minimum(t / max(attack, 1e-4), 1)


def pluck(freq, decay=0.6, brightness=0.5, attack=0.0):
    """Plucked string (Karplus-Strong). Computed 4x oversampled for accurate pitch."""
    os_sr = SR * 4
    damping = 0.5 - 0.45 * np.clip(brightness, 0, 1)     # less damping = brighter
    period = os_sr / freq - damping
    N = max(int(period), 2)
    frac = period - N
    g = np.exp(-1.0 / (decay * freq))                    # loss per period
    n = int(os_sr * decay * 5)
    rng = np.random.default_rng(int(freq * 100))
    x = np.zeros(n)
    x[:N] = rng.uniform(-1, 1, N)
    a = np.zeros(N + 3)
    a[0] = 1
    # y[n] = x[n] + g * ((1-d) * y[n-N] + d * y[n-N-1]), with a tiny fractional-delay blend
    a[N] -= g * (1 - damping) * (1 - frac)
    a[N + 1] -= g * ((1 - damping) * frac + damping * (1 - frac))
    a[N + 2] -= g * damping * frac
    y = signal.lfilter([1.0], a, x)
    y = signal.resample_poly(y, 1, 4)
    return y / (np.abs(y).max() + 1e-9)


def sine(freq, decay=0.5, brightness=0.5, attack=0.01):
    """Soft tone; brightness adds a little 2nd and 3rd harmonic."""
    n = int(SR * decay * 5)
    env, t = _env(n, attack, decay)
    ph = 2 * np.pi * freq * t
    return (np.sin(ph) + 0.4 * brightness * np.sin(2 * ph) + 0.15 * brightness * np.sin(3 * ph)) * env


BUILTIN_NOTES = {"marimba": marimba, "bell": bell, "pluck": pluck, "sine": sine}


class NoteInstrument:
    """freq (Hz) -> mono sound, from a built-in synth or a WAV sample. Cached per note."""

    def __init__(self, cfg, base_dir, layer):
        self.cfg, self.cache = cfg, {}
        if cfg.get("sample"):
            self.sample = load_sample(cfg["sample"], base_dir)
            self.root_hz = float(synth.midi_to_hz(note_to_midi(cfg["root"])))
            self.fn = None
        else:
            name = cfg["instrument"]
            if name not in BUILTIN_NOTES:
                raise SystemExit(f"[{layer}] unknown instrument '{name}'. "
                                 f"Choose one of: {', '.join(BUILTIN_NOTES)} - or set sample = \"samples/....wav\"")
            self.fn = BUILTIN_NOTES[name]

    def __call__(self, freq):
        key = round(float(freq), 2)
        if key not in self.cache:
            c = self.cfg
            if self.fn:
                x = self.fn(freq, decay=c["decay"], brightness=c["brightness"], attack=c["attack"])
            else:
                x = repitch(self.sample, freq / self.root_hz) if c["pitched"] else self.sample
                if c["length"] and len(x) > c["length"] * SR:
                    x = fade_out(x[: int(c["length"] * SR)], min(0.05, c["length"] / 4))
            self.cache[key] = x
        return self.cache[key]


# --- thunder: texture + boom ---------------------------------------------------------

def texture(cfg, n, base_dir, seed):
    """Continuous sound of length n (mono, peak ~1)."""
    if cfg.get("sample"):
        return loop_to_length(load_sample(cfg["sample"], base_dir), n)
    kind = cfg["texture"]
    if kind == "rumble":
        return synth.rumble(n, cutoff=cfg["cutoff"], seed=seed)
    if kind == "noise":
        x = np.random.default_rng(seed).standard_normal(n)
        sos = signal.butter(2, [cfg["low"], cfg["high"]], "bandpass", fs=SR, output="sos")
        x = signal.sosfilt(sos, x)
        return x / (np.abs(x).max() + 1e-9)
    raise SystemExit(f"[thunder] unknown texture '{kind}'. Choose: {', '.join(TEXTURES)} - or set sample = \"...wav\"")


def boom(cfg, base_dir):
    if cfg.get("boom_sample"):
        return load_sample(cfg["boom_sample"], base_dir)
    if cfg["boom"] != "boom":
        raise SystemExit(f"[thunder] unknown boom '{cfg['boom']}'. Use \"boom\" or set boom_sample = \"...wav\"")
    src = synth.rumble(int(cfg["boom_decay"] * 4 * SR), cutoff=160, seed=3)
    t = np.arange(len(src)) / SR
    return src * np.exp(-t / cfg["boom_decay"]) * np.minimum(t / 0.02, 1)
