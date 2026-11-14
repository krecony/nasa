"""Earth Jukebox: turn a NASA Earth visualization video into music.

Usage:
    py sonify.py imerg videos/imergert_1080p_30.mp4
    py sonify.py gmao_t2m videos/gmao_t2m_2048x1024.mp4
    py sonify.py imerg videos/imergert_1080p_30.mp4 --no-video        skip the website video (faster)
    py sonify.py imerg videos/imergert_1080p_30.mp4 --only drops,pad  hear only some layers
    py sonify.py imerg videos/imergert_1080p_30.mp4 --stems           also save each layer as a WAV
    py sonify.py imerg videos/imergert_1080p_30.mp4 --sounds sounds/my_version.toml

The video analysis is cached (output/<preset>/analysis.pkl), so after the first
run, changing sounds only takes a few seconds. Use --reanalyze to force it.

Writes:
    output/<preset>/sonification.wav     the soundtrack
    output/<preset>/stems/*.wav          each layer on its own (with --stems)
    output/<preset>/features.csv         the numbers behind it, per frame
    output/<preset>/features.png         plot of the features (check this first!)
    output/<preset>/descriptions.vtt     one sentence per day, for accessibility
    website/media/<preset>.mp4           slowed-down video + soundtrack (needs ffmpeg)
    website/media/<preset>.vtt / .png    copies for the website
    website/tracks.json                  the jukebox's track list (updated)
"""

import argparse
import hashlib
import json
import pickle
import shutil
import subprocess
import sys
from pathlib import Path

from scipy.io import wavfile

from jukebox import compose, compose_field
from jukebox.config import LAYERS_BY_KIND, load_sounds
from jukebox.describe import day_cues, field_cues, write_vtt, write_csv, write_field_csv
from jukebox.features import extract
from jukebox.field import extract_field
from jukebox.plots import plot_features, plot_field
from jukebox.presets import PRESETS
from jukebox.synth import SAMPLE_RATE
from jukebox.timeline import build_timeline

ROOT = Path(__file__).resolve().parent
ANALYSIS_KEYS = ["kind", "map", "layers", "color_match", "min_background_diff", "ignore", "heavy_threshold",
                 "colorbar", "max_color_distance", "hot_threshold", "cold_threshold", "very_cold_threshold"]


def analysis_key(preset, video):
    """Changes whenever the video or the analysis settings change."""
    st = video.stat()
    blob = json.dumps({k: preset.get(k) for k in ANALYSIS_KEYS}, sort_keys=True, default=str)
    cb = preset.get("colorbar", {}).get("image")
    if cb and (ROOT / cb).exists():
        blob += str((ROOT / cb).stat().st_mtime)
    return hashlib.sha1(f"{video.name}|{st.st_size}|{st.st_mtime}|{blob}|v3".encode()).hexdigest()


def analyze(preset, video, out, force):
    cache = out / "analysis.pkl"
    key = analysis_key(preset, video)
    if cache.exists() and not force:
        try:
            data = pickle.loads(cache.read_bytes())
            if data["key"] == key:
                print("1/5 Using cached video analysis (--reanalyze to redo it)")
                return data["info"], data["layers"], data["feats"]
        except Exception:
            pass
    print("1/5 Reading frames and extracting features (about 20 s)...")
    if preset.get("kind") == "field":
        fx, feats = extract_field(preset, video, ROOT)
    else:
        fx, feats = extract(preset, video)
    cache.write_bytes(pickle.dumps({"key": key, "info": fx.info, "layers": fx.layers, "feats": feats}))
    return fx.info, fx.layers, feats


def make_video(video, wav, out, slow, tail, smooth=False):
    if not shutil.which("ffmpeg"):
        print("! ffmpeg not found: skipping the video. Install it (e.g. `winget install ffmpeg`) and run again.")
        return False
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(video), "-i", str(wav),
        "-filter:v", f"setpts={slow}*PTS,tpad=stop_mode=clone:stop_duration={tail}"
                     + (",framerate=fps=30" if smooth else ""),
        "-r", "30", "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        str(out),
    ]
    subprocess.run(cmd, check=True)
    return True


def update_tracks(preset, has_video):
    path = ROOT / "website" / "tracks.json"
    tracks = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    pid = preset["id"]
    old = next((t for t in tracks if t["id"] == pid), {})
    entry = {
        "id": pid,
        "title": preset["title"],
        "source": preset["source"],
        "description": preset["description"],
        "listening_guide": preset["listening_guide"],
        "video": f"media/{pid}.mp4" if has_video else old.get("video"),
        "captions": f"media/{pid}.vtt",
        "features_image": f"media/{pid}.png",
    }
    tracks = [t for t in tracks if t["id"] != pid] + [entry]
    path.write_text(json.dumps(tracks, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("preset", choices=sorted(PRESETS))
    ap.add_argument("video")
    ap.add_argument("--sounds", help="sound settings file (default: the preset's, e.g. sounds/imerg.toml)")
    ap.add_argument("--only", help="comma-separated layers to keep (see the sounds file, e.g. drops,pad)")
    ap.add_argument("--stems", action="store_true", help="also save every layer as its own WAV")
    ap.add_argument("--no-video", action="store_true", help="don't build the website video")
    ap.add_argument("--reanalyze", action="store_true", help="ignore the cached video analysis")
    ap.add_argument("--seed", type=int, default=0, help="random seed for drop timing")
    args = ap.parse_args()

    preset = PRESETS[args.preset]
    kind = preset.get("kind", "categories")
    layers_ok = LAYERS_BY_KIND[kind]
    video = Path(args.video)
    if not video.exists():
        sys.exit(f"Video not found: {video}")
    sounds_path = Path(args.sounds) if args.sounds else ROOT / preset["sounds"]
    snd = load_sounds(sounds_path, kind)
    only = None
    if args.only:
        only = [s.strip() for s in args.only.split(",") if s.strip()]
        bad = [s for s in only if s not in layers_ok]
        if bad:
            sys.exit(f"--only: unknown layer(s) {', '.join(bad)}. Choose from: {', '.join(layers_ok)}")

    out = ROOT / "output" / preset["id"]
    media = ROOT / "website" / "media"
    out.mkdir(parents=True, exist_ok=True)
    media.mkdir(parents=True, exist_ok=True)

    info, layers, feats = analyze(preset, video, out, args.reanalyze)
    tl = build_timeline(feats, preset, info["fps"])
    print(f"    {tl['n_frames']} frames, data until {tl['dates'][tl['data_end'] - 1]:%Y-%m-%d %H:%M} UTC, "
          f"{len(tl['day_starts'])} days, soundtrack {tl['duration']:.1f} s")

    print("2/5 Plotting features and writing CSV...")
    day_lines = [tl["frame_time"][d] for d in tl["day_starts"]]
    if kind == "field":
        plot_field(feats, tl["frame_time"], out / "features.png", day_starts=day_lines, units=preset.get("units", ""))
        write_field_csv(feats, tl, out / "features.csv")
    else:
        plot_features(feats, tl["frame_time"], layers, out / "features.png", day_starts=day_lines)
        write_csv(feats, tl, layers, out / "features.csv")

    print(f"3/5 Composing the soundtrack with {sounds_path.name}"
          + (f" (only: {', '.join(only)})" if only else "") + "...")
    composer = compose_field if kind == "field" else compose
    audio, stems = composer.render(feats, preset, tl, snd, seed=args.seed, only=only)
    wavfile.write(out / "sonification.wav", SAMPLE_RATE, audio)
    if args.stems:
        (out / "stems").mkdir(exist_ok=True)
        for name, s in stems.items():
            wavfile.write(out / "stems" / f"{name}.wav", SAMPLE_RATE, s)
        print(f"    stems: {', '.join(stems)} -> {out / 'stems'}")

    print("4/5 Writing descriptions...")
    cues = field_cues(feats, tl, preset) if kind == "field" else day_cues(feats, tl)
    write_vtt(cues, out / "descriptions.vtt")

    has_video = False
    if args.no_video:
        print("5/5 Skipping the website video (--no-video)")
    elif only:
        print("5/5 Skipping the website video (--only is for testing)")
    else:
        print("5/5 Building the website video (ffmpeg)...")
        has_video = make_video(video, out / "sonification.wav", media / f"{preset['id']}.mp4",
                               preset["slow_down"], tail=len(audio) / SAMPLE_RATE - tl["duration"],
                               smooth=preset.get("smooth_video", False))
    shutil.copy(out / "descriptions.vtt", media / f"{preset['id']}.vtt")
    shutil.copy(out / "features.png", media / f"{preset['id']}.png")
    update_tracks(preset, has_video)
    print(f"Done. Listen to {out / 'sonification.wav'}")


if __name__ == "__main__":
    sys.exit(main())
