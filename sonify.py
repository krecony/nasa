"""Earth Jukebox: turn a NASA Earth visualization video into music.

Every track is a folder in tracks/ (see tracks/README.md). Usage:
    py sonify.py WindSpeed                    build one track (its video is in tracks/WindSpeed/)
    py sonify.py imerg gmao_t2m               build several
    py sonify.py --all                        build every track
    py sonify.py --list                       show the tracks
    py sonify.py WindSpeed --no-video         skip the website video (faster, for tweaking sounds)
    py sonify.py imerg --only drops,pad       hear only some layers
    py sonify.py imerg --stems                also save each layer as a WAV
    py sonify.py imerg --sounds tracks/imerg/sounds_samples_demo.toml   try another sound file
    py sonify.py imerg --video somewhere/else.mp4                        use another copy of the video
(The old form `py sonify.py imerg videos/imergert_1080p_30.mp4` still works.)

The video analysis is cached (output/<track>/analysis.pkl), so after the first
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
import re
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
from jukebox.webbundle import make_bundle
from jukebox.tracks import ANALYSIS_KEYS, all_track_names, find_video, load_track, VIDEO_TYPES
from jukebox.synth import SAMPLE_RATE
from jukebox.timeline import build_timeline

ROOT = Path(__file__).resolve().parent


def analysis_key(preset, video):
    """Changes whenever the video or the analysis settings change."""
    st = video.stat()
    blob = json.dumps({k: preset.get(k) for k in ANALYSIS_KEYS}, sort_keys=True, default=str)
    cb = (preset.get("colorbar") or {}).get("image")
    if cb and Path(cb).exists():
        blob += str(Path(cb).stat().st_mtime)
    return hashlib.sha1(f"{video.name}|{st.st_size}|{st.st_mtime}|{blob}|v5".encode()).hexdigest()


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


def build(name, args, video_override=None):
    """Build one track: analysis -> plot/CSV -> soundtrack -> descriptions -> website video."""
    preset = load_track(name)
    kind = preset.get("kind", "categories")
    layers_ok = LAYERS_BY_KIND[kind]
    video = find_video(preset["folder"], preset, video_override or args.video)
    sounds_path = Path(args.sounds) if args.sounds else Path(preset["sounds"])
    if not sounds_path.exists():
        sys.exit(f"Sound settings not found: {sounds_path}")
    snd = load_sounds(sounds_path, kind, track_folder=preset["folder"], preset=preset)
    if kind == "field":
        layers_ok = [c["name"] for c in snd["sounds"]]
    only = None
    if args.only:
        only = [s.strip() for s in args.only.split(",") if s.strip()]
        bad = [s for s in only if s not in layers_ok]
        if bad:
            what = "sound" if kind == "field" else "layer"
            sys.exit(f"--only: unknown {what}(s) {', '.join(bad)}. Choose from: {', '.join(layers_ok)}")

    out = ROOT / "output" / preset["id"]
    media = ROOT / "website" / "media"
    out.mkdir(parents=True, exist_ok=True)
    media.mkdir(parents=True, exist_ok=True)
    print(f"== {preset['id']}: {preset['title']}  (video: {video.name})")

    info, layers, feats = analyze(preset, video, out, args.reanalyze)
    tl = build_timeline(feats, preset, info["fps"])
    print(f"    {tl['n_frames']} frames, data until {tl['dates'][tl['data_end'] - 1]:%Y-%m-%d %H:%M} UTC, "
          f"{len(tl['day_starts'])} days, soundtrack {tl['duration']:.1f} s")

    print("2/5 Plotting features and writing CSV...")
    day_lines = [tl["frame_time"][d] for d in tl["day_starts"]]
    if kind == "field":
        plot_field(feats, tl["frame_time"], out / "features.png", day_starts=day_lines, units=preset.get("units", ""),
                   hot=preset.get("hot_threshold"), cold=preset.get("cold_threshold"))
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
        for old_stem in (out / "stems").glob("*.wav"):     # don't leave stems of removed sounds lying around
            old_stem.unlink()
        for sname, st in stems.items():
            safe = re.sub(r"[^\w.-]+", "_", sname)
            wavfile.write(out / "stems" / f"{safe}.wav", SAMPLE_RATE, st)
        print(f"    stems: {', '.join(stems)} -> {out / 'stems'}")

    print("4/5 Writing descriptions...")
    cues = field_cues(feats, tl, preset) if kind == "field" else day_cues(feats, tl)
    write_vtt(cues, out / "descriptions.vtt")

    has_video = False
    if args.no_video or args.no_publish:
        print("5/5 Skipping the website video (--no-video)")
    elif only:
        print("5/5 Skipping the website video (--only is for testing)")
    else:
        print("5/5 Building the website video (ffmpeg)...")
        has_video = make_video(video, out / "sonification.wav", media / f"{preset['id']}.mp4",
                               preset["slow_down"], tail=len(audio) / SAMPLE_RATE - tl["duration"],
                               smooth=preset.get("smooth_video", False))
    if args.no_publish:
        print("    (preview only: the website was not changed)")
    else:
        shutil.copy(out / "descriptions.vtt", media / f"{preset['id']}.vtt")
        shutil.copy(out / "features.png", media / f"{preset['id']}.png")
        update_tracks(preset, has_video)
        make_bundle()                         # keep the browser's copy of the code up to date
    print(f"Done. Listen to {out / 'sonification.wav'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tracks", nargs="*", help="track name(s): folders in tracks/")
    ap.add_argument("--all", action="store_true", help="build every track")
    ap.add_argument("--list", action="store_true", help="list the tracks and whether their video is there")
    ap.add_argument("--video", help="use this video file instead of the one in the track folder")
    ap.add_argument("--sounds", help="sound settings file (default: tracks/<name>/sounds.toml)")
    ap.add_argument("--only", help="comma-separated layers to keep (see the sounds file, e.g. drops,pad)")
    ap.add_argument("--stems", action="store_true", help="also save every layer as its own WAV")
    ap.add_argument("--no-video", action="store_true", help="don't build the website video")
    ap.add_argument("--no-publish", action="store_true", help="preview only: don't touch the website at all")
    ap.add_argument("--reanalyze", action="store_true", help="ignore the cached video analysis")
    ap.add_argument("--seed", type=int, default=0, help="random seed for drop timing")
    args = ap.parse_args()

    names = list(args.tracks)
    legacy_video = None
    # old form: py sonify.py imerg videos/imergert_1080p_30.mp4
    if len(names) == 2 and Path(names[1]).suffix.lower() in VIDEO_TYPES:
        names, legacy_video = names[:1], names[1]

    if args.list:
        for n in all_track_names():
            try:
                v = find_video(load_track(n)["folder"], load_track(n)).name
            except SystemExit:
                v = "NO VIDEO YET"
            print(f"  {n:<14} {load_track(n)['title']}  [{v}]")
        return
    if args.all:
        names = all_track_names()
    if not names:
        ap.print_help()
        print("\nTracks:", ", ".join(all_track_names()) or "none yet")
        return
    if len(names) > 1 and (args.sounds or args.video):
        sys.exit("--sounds and --video only work with one track at a time.")

    failed = []
    for n in names:
        try:
            build(n, args, legacy_video)
        except SystemExit as e:
            if len(names) == 1:
                raise
            print(f"! {n} skipped: {e}")
            failed.append(n)
    if len(names) > 1:
        print(f"\nBuilt {len(names) - len(failed)} of {len(names)} tracks" + (f"; skipped: {', '.join(failed)}" if failed else "."))


if __name__ == "__main__":
    sys.exit(main())
