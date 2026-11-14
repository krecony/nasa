"""Low-level sound helpers: notes/scales, panning, pad tone, rumble, reverb.

The playable instruments (incl. your own WAV files) are in instruments.py.

Everything here works on float arrays at SAMPLE_RATE samples per second.
Stereo buffers have shape (n_samples, 2).
"""

import numpy as np
from scipy import signal

SAMPLE_RATE = 44100
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
SCALES = {
    "major_pentatonic": [0, 2, 4, 7, 9],
    "minor_pentatonic": [0, 3, 5, 7, 10],
    "major": [0, 2, 4, 5, 7, 9, 11],
    "minor": [0, 2, 3, 5, 7, 8, 10],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "lydian": [0, 2, 4, 6, 7, 9, 11],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "harmonic_minor": [0, 2, 3, 5, 7, 8, 11],
    "blues": [0, 3, 5, 6, 7, 10],
    "whole_tone": [0, 2, 4, 6, 8, 10],
    "chromatic": list(range(12)),
}


def midi_to_hz(m):
    return 440.0 * 2 ** ((np.asarray(m, dtype=float) - 69) / 12)


def note_midi(name, octave):
    return 12 * (octave + 1) + NOTE_NAMES.index(name)


def pan_gains(pan):
    """Equal-power panning. pan -1 = left, +1 = right."""
    a = (np.clip(pan, -1, 1) + 1) * np.pi / 4
    return np.cos(a), np.sin(a)


def add_mono(buf, mono, start_s, pan=0.0, gain=1.0):
    """Mix a mono sound into a stereo buffer at a time (seconds) and pan."""
    i0 = int(start_s * SAMPLE_RATE)
    if i0 >= len(buf):
        return
    seg = mono[: len(buf) - i0] * gain
    gl, gr = pan_gains(pan)
    buf[i0:i0 + len(seg), 0] += seg * gl
    buf[i0:i0 + len(seg), 1] += seg * gr


# --- continuous sounds -------------------------------------------------------

def pad_voice(freqs_per_sample, amp_per_sample, harmonics=(1.0, 0.45, 0.25, 0.12), detune_cents=7):
    """Warm sustained tone that can glide: frequency and amplitude given per sample.

    Phase is the running sum of frequency, so changing pitch doesn't click.
    Two copies slightly detuned give a gentle chorus.
    """
    out = np.zeros(len(freqs_per_sample))
    for d in (-detune_cents, detune_cents):
        f = freqs_per_sample * 2 ** (d / 1200)
        phase = 2 * np.pi * np.cumsum(f) / SAMPLE_RATE
        for k, a in enumerate(harmonics, start=1):
            out += a * np.sin(k * phase)
    return out * amp_per_sample / (2 * sum(harmonics))


def rumble(n, cutoff=110, seed=1):
    """Low thunder-like noise: brown noise through a low-pass filter."""
    rng = np.random.default_rng(seed)
    x = np.cumsum(rng.standard_normal(n))
    x = signal.sosfilt(signal.butter(2, 20, "highpass", fs=SAMPLE_RATE, output="sos"), x)
    x = signal.sosfilt(signal.butter(4, cutoff, "lowpass", fs=SAMPLE_RATE, output="sos"), x)
    return x / (np.abs(x).max() + 1e-9)


def reverb(stereo, seconds=2.4, wet=0.3, seed=7):
    """Cheap hall reverb: convolve with exponentially decaying noise."""
    rng = np.random.default_rng(seed)
    n = int(seconds * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    env = np.exp(-t * 6.9 / seconds)                       # -60 dB at `seconds`
    lp = signal.butter(1, 5000, "lowpass", fs=SAMPLE_RATE, output="sos")
    out = np.zeros_like(stereo)
    for ch in range(2):
        ir = signal.sosfilt(lp, rng.standard_normal(n)) * env
        ir /= np.sqrt((ir ** 2).sum())
        out[:, ch] = signal.fftconvolve(stereo[:, ch], ir)[: len(stereo)]
    return (1 - wet) * stereo + wet * out

