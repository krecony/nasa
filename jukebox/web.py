"""The studio in a visitor's browser (public website), run by Pyodide (Python compiled for the browser).

The same code as `py studio.py` and `py sonify.py`, with three differences:
- The browser reads the video (Python in the browser can't decode MP4s). It sends the frame
  shown in the form with set_frame(), and every frame during a build with add_frame().
  The video file itself stays in the browser's storage; the track folder only gets video.json
  (name, size, frames per second).
- Track folders live in the browser's storage (tracks/ is kept in IndexedDB by the page).
- A build makes the soundtrack and captions, but no graph and no combined video file:
  the jukebox plays the original video slowed down, with the soundtrack in sync.

The page calls: handle() for every studio request (same routes as studio.py), set_video(),
set_frame(), and begin() / add_frame() / finish() for a build.
Bytes come from JavaScript as Uint8Array (or bytes, when testing with normal Python).
"""

import hashlib
import json
import pickle
import shutil
import uuid

import numpy as np

from . import compose_field
from . import studio_core as core
from .config import load_sounds
from .describe import field_cues, vtt_time
from .field import WORK_H, WORK_W, FieldExtractor, finish_field
from .synth import SAMPLE_RATE
from .timeline import build_timeline
from .tracks import ANALYSIS_KEYS, TRACKS_DIR, load_track

VIDEO_JSON = "video.json"          # what the browser told us about the video
CACHE = "analysis.pkl"             # the video analysis, so changing only the sounds is quick
JOBS = {}


def _bytes(x):
    """Uint8Array from JavaScript (a JsProxy), or bytes when testing with normal Python."""
    if x is None:
        return b""
    if isinstance(x, (bytes, bytearray, memoryview)):
        return bytes(x)
    return x.to_bytes()


def _rgb(rgba, w, h):
    return np.frombuffer(_bytes(rgba), np.uint8).reshape(int(h), int(w), 4)[:, :, :3]


class BrowserHooks(core.FileHooks):
    mode = "browser"

    def __init__(self):
        self.frame = None          # (track, frame index, RGB array) of the frame shown in the form

    def video_name(self, folder, cfg):
        f = folder / VIDEO_JSON
        if not f.exists():
            raise core.Problem("Upload the video first (section 2).")
        return json.loads(f.read_text(encoding="utf-8"))["name"]

    def video_info(self, tid):
        f = core.any_folder(tid) / VIDEO_JSON
        if not f.exists():
            raise core.Problem("Upload the video first (section 2).")
        return json.loads(f.read_text(encoding="utf-8"))

    def read_frame(self, tid, index):
        if not self.frame or self.frame[0] != tid:
            raise core.Problem("The video frame isn't ready yet: wait a moment and try again.")
        return self.frame[2]

    def save_video(self, tid, folder, name, data):
        raise core.Problem("In the browser, the page keeps the video itself.")

    def shared_samples(self):
        return []                  # the team's samples/ folder isn't part of the public website

    def build(self, tid, body):
        raise core.Problem("In the browser, builds go through begin() / add_frame() / finish().")

    def delete(self, tid):
        shutil.rmtree(TRACKS_DIR / tid, ignore_errors=True)
        return {"ok": True}


def setup():
    core.HOOKS = BrowserHooks()
    TRACKS_DIR.mkdir(parents=True, exist_ok=True)
    return "ok"


def handle(method, path, query_json="{}", body=None):
    """One studio request, like the server's /api/... -> (status, content type, bytes, download name)."""
    try:
        return core.route(method, path, json.loads(query_json or "{}"), _bytes(body))
    except Exception as e:      # shown in the form instead of a silent failure
        import traceback
        traceback.print_exc()
        return 500, "application/json", json.dumps({"error": f"Something went wrong: {e}"}).encode(), None


def set_video(tid, info_json):
    """The visitor picked a video: remember its name, size and frames per second."""
    folder = TRACKS_DIR / core.check_id(tid)
    folder.mkdir(parents=True, exist_ok=True)
    info = json.loads(info_json)
    info = {"name": str(info["name"]), "fps": float(info["fps"]), "frames": int(info["frames"]),
            "width": int(info["width"]), "height": int(info["height"]), "seconds": float(info["seconds"]),
            "fps_detected": float(info.get("fps_detected") or info["fps"])}
    (folder / VIDEO_JSON).write_text(json.dumps(info), encoding="utf-8")
    core.forget_video_name(folder)
    return json.dumps(info)


def set_frame(tid, index, rgba, w, h):
    """The frame shown in the form (full size), for "check what a color reads as" and the value map."""
    core.HOOKS.frame = (tid, int(index), _rgb(rgba, w, h).copy())
    return "ok"


# ---------------------------------------------------------------- builds

def analysis_key(preset, folder):
    blob = json.dumps({k: preset.get(k) for k in ANALYSIS_KEYS}, sort_keys=True, default=str)
    cb = (preset.get("colorbar") or {}).get("image")
    h = hashlib.sha1(blob.encode())
    h.update((folder / VIDEO_JSON).read_bytes())
    if cb:
        try:
            h.update(open(cb, "rb").read())
        except OSError:
            pass
    return h.hexdigest() + "|web1"


def begin(tid, mode="preview", only_json="[]"):
    """Start a build. Says whether the page has to send the frames (or the analysis is cached)."""
    folder = core.folder_of(tid)
    info = core.HOOKS.video_info(tid)
    preset = load_track(tid)
    if preset.get("kind") != "field":
        raise core.Problem("Only 'value everywhere' tracks can be built in the browser.")
    snd = load_sounds(folder / "sounds.toml", "field", folder, preset)
    only = [n for n in json.loads(only_json or "[]") if n] or None
    if only:
        names = [c["name"] for c in snd["sounds"]]
        only = [n for n in only if n in names] or None
    key = analysis_key(preset, folder)
    job = {"id": uuid.uuid4().hex[:10], "tid": tid, "mode": mode, "only": only, "preset": preset, "snd": snd,
           "info": info, "key": key, "feats": None}
    cache = folder / CACHE
    if cache.exists():
        try:
            data = pickle.loads(cache.read_bytes())
            if data["key"] == key:
                job["feats"] = data["feats"]
        except Exception:
            pass
    if job["feats"] is None:
        job["fx"] = FieldExtractor(preset, None, core.ROOT, info=info)
        job["new_feats"] = []
    JOBS[job["id"]] = job
    return json.dumps({"job": job["id"], "need_frames": job["feats"] is None, "frames": info["frames"],
                       "fps": info["fps"], "work": [WORK_W, WORK_H]})


def add_frame(jid, rgba, w, h):
    """One video frame (sent at WORK_W x WORK_H, nearest-neighbour scaled, like the desktop version)."""
    job = JOBS[jid]
    job["new_feats"].append(job["fx"].frame_features(np.ascontiguousarray(_rgb(rgba, w, h))))
    return len(job["new_feats"])


def finish(jid):
    """Make the soundtrack and captions. Returns (details as JSON, WAV bytes)."""
    job = JOBS.pop(jid)
    preset, info, folder = job["preset"], job["info"], core.folder_of(job["tid"])
    if job["feats"] is None:
        if len(job["new_feats"]) < 2:
            raise core.Problem("Couldn't read the video's frames.")
        _, feats = finish_field(job["fx"], job["new_feats"])
        (folder / CACHE).write_bytes(pickle.dumps({"key": job["key"], "feats": feats}))
        job["feats"] = feats
    feats = job["feats"]

    tl = build_timeline(feats, preset, info["fps"])
    audio, _ = compose_field.render(feats, preset, tl, job["snd"], seed=0, only=job["only"])
    cues = field_cues(feats, tl, preset)
    slow = float(preset["slow_down"])
    # 16-bit WAV: half the size, and every browser plays it
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    wav = _wav_bytes(pcm, SAMPLE_RATE)
    details = {
        "id": job["tid"], "mode": job["mode"],
        "title": preset["title"], "source": preset["source"], "description": preset["description"],
        "listening_guide": preset["listening_guide"], "slow_down": slow, "units": preset.get("units", ""),
        "duration": len(audio) / SAMPLE_RATE, "video_seconds": tl["duration"] / slow,
        "days": len(tl["day_starts"]), "frames": tl["n_frames"],
        "captions": _vtt(cues, 1.0),            # soundtrack time
        "captions_video": _vtt(cues, 1 / slow),  # video time (the jukebox plays the original video slowed down)
        "log": [f"{tl['n_frames']} frames, data until {tl['dates'][tl['data_end'] - 1]:%Y-%m-%d %H:%M} UTC, "
                f"{len(tl['day_starts'])} days, soundtrack {len(audio) / SAMPLE_RATE:.1f} s"],
    }
    return json.dumps(details), wav


def _vtt(cues, scale):
    lines = ["WEBVTT", ""]
    for i, (a, b, text) in enumerate(cues, 1):
        lines += [str(i), f"{vtt_time(a * scale)} --> {vtt_time(b * scale)}", text, ""]
    return "\n".join(lines)


def _wav_bytes(pcm, rate):
    import io
    from scipy.io import wavfile
    buf = io.BytesIO()
    wavfile.write(buf, rate, pcm)
    return buf.getvalue()
