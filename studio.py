"""Earth Jukebox studio: the website plus a form to add and edit tracks.

    py studio.py               then open http://localhost:8000
    py studio.py --port 8080   use another port

It serves the website exactly like `py -m http.server` (from the website folder) and adds:
    /studio/     the Add / Edit track form
    /api/...     what the form talks to (save, upload, build, export, import, delete)
    /output/...  preview files (soundtrack, graph, captions)

Everything stays on this computer: the server only listens to this computer (127.0.0.1).
On the public website (GitHub Pages etc.) the studio simply isn't there.
"""

import argparse
import io
import json
import mimetypes
import re
import shutil
import subprocess
import sys
import threading
import time
import tomllib
import traceback
import uuid
import zipfile
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import cv2
import numpy as np

from jukebox import synth
from jukebox.colorbar import find_bar, read_colorbar
from jukebox.config import FIELD_GLOBAL, SOUND_DEFAULTS, load_sounds
from jukebox.field import LUT_BITS, build_lut
from jukebox.instruments import BUILTIN_NOTES, TEXTURES, load_sample
from jukebox.tomlwriter import SOUND_HELP, sounds_toml, track_toml
from jukebox.tracks import KNOWN, ROOT, TRACKS_DIR, VIDEO_TYPES, all_track_names, find_video, load_track

WEB, STUDIO, OUT = ROOT / "website", ROOT / "studio", ROOT / "output"
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,40}$")
FILE_RE = re.compile(r"[^A-Za-z0-9._#-]+")
JOBS, JOBS_LOCK = {}, threading.Lock()
LUT_CACHE, LUT_LOCK = {}, threading.Lock()


class Problem(Exception):
    """Something the user can fix: shown in the form."""

    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


def check_id(tid):
    if not tid or not ID_RE.match(tid):
        raise Problem("Use a short name with only letters, numbers, - and _ (no spaces), e.g. SeaSurface.")
    return tid


def folder_of(tid, must_exist=True):
    d = TRACKS_DIR / check_id(tid)
    if must_exist and not (d / "track.toml").exists():
        raise Problem(f"There's no track called '{tid}'.", 404)
    return d


def any_folder(tid):
    """The track's folder, also for a new track that has files but no saved settings yet."""
    d = TRACKS_DIR / check_id(tid)
    if not d.exists():
        raise Problem("Upload the video first.", 404)
    return d


def raw_cfg(folder):
    f = folder / "track.toml"
    return tomllib.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def safe_name(name, default):
    name = FILE_RE.sub("_", Path(name or default).name).strip("._") or default
    return name[:80]


def jsonable(x):
    if isinstance(x, dict):
        return {k: jsonable(v) for k, v in x.items() if not k.startswith("_")}
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    if isinstance(x, Path):
        return str(x)
    if isinstance(x, (np.floating, np.integer)):
        return x.item()
    return x


# ---------------------------------------------------------------- reading tracks

def studio_info():
    tracks = []
    for name in all_track_names():
        item = {"id": name}
        try:
            t = load_track(name)
            item.update(title=t["title"], kind=t["kind"], editable=t["kind"] == "field")
            try:
                item["video"] = find_video(t["folder"], t).name
            except SystemExit:
                item["video"] = None
        except SystemExit as e:
            item.update(title=name, error=str(e), editable=False)
        tracks.append(item)
    return {
        "tracks": tracks,
        "shared_samples": sorted(f"samples/{p.name}" for p in (ROOT / "samples").glob("*.wav")),
        "instruments": list(BUILTIN_NOTES), "textures": TEXTURES,
        "scales": list(synth.SCALES), "keys": synth.NOTE_NAMES,
        "sound_defaults": SOUND_DEFAULTS, "sound_help": SOUND_HELP, "music_defaults": FIELD_GLOBAL,
        "track_defaults": {k: v for k, v in KNOWN.items() if v is not None},
    }


def track_samples(folder):
    d = folder / "samples"
    return sorted(f"samples/{p.name}" for p in d.glob("*.wav")) if d.exists() else []


def get_track(tid):
    folder = folder_of(tid)
    raw = tomllib.loads((folder / "track.toml").read_text(encoding="utf-8"))
    t = load_track(tid)
    out = {"id": tid, "track": raw, "kind": t["kind"], "editable": t["kind"] == "field",
           "colorbar": (folder / (raw.get("colorbar") or {}).get("image", "colorbar.png")).exists(),
           "samples": track_samples(folder)}
    try:
        out["video"] = find_video(folder, t).name
    except SystemExit:
        out["video"] = None
    if t["kind"] == "field" and (folder / "sounds.toml").exists():
        snd = load_sounds(folder / "sounds.toml", "field", folder, t)
        out["sounds"] = {"music": snd["music"], "mix": snd["mix"], "sounds": snd["sounds"]}
    return jsonable(out)


def video_info(tid):
    folder = any_folder(tid)
    try:
        path = find_video(folder, raw_cfg(folder))
    except SystemExit as e:
        raise Problem(str(e))
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise Problem(f"Can't open the video {path.name}.")
    info = {"name": path.name, "fps": cap.get(cv2.CAP_PROP_FPS),
            "frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
            "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}
    cap.release()
    info["seconds"] = info["frames"] / info["fps"] if info["fps"] else 0
    return info


def read_frame(tid, index=0):
    """RGB frame of the track's video."""
    folder = any_folder(tid)
    try:
        path = find_video(folder, raw_cfg(folder))
    except SystemExit as e:
        raise Problem(str(e))
    cap = cv2.VideoCapture(str(path))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, min(int(index), total - 1)))
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise Problem("Couldn't read a frame from the video.")
    return frame[:, :, ::-1]


def png(rgb):
    ok, buf = cv2.imencode(".png", np.ascontiguousarray(rgb[:, :, ::-1]))
    return buf.tobytes()


# ---------------------------------------------------------------- colors

def colorbar_spec(tid, s):
    """The form's color settings -> what read_colorbar needs (image path in the track folder)."""
    folder = any_folder(tid)
    cb = dict(s.get("colorbar") or {})
    img = folder / safe_name(cb.get("image") or "colorbar.png", "colorbar.png")
    if not img.exists():
        raise Problem("Upload a color bar image first.")
    for k in ("min", "max"):
        if cb.get(k) in (None, ""):
            raise Problem("Fill in the color bar's min and max values.")
        cb[k] = float(cb[k])
    cb["image"] = str(img)
    for k in ("ignore_above", "ignore_below"):
        if cb.get(k) in ("", None):
            cb.pop(k, None)
    return cb


def colorbar_info(tid, s):
    cb = colorbar_spec(tid, s)
    try:
        colors, values = read_colorbar(cb, ROOT)
    except SystemExit as e:
        raise Problem(str(e))
    img = cv2.imread(cb["image"], cv2.IMREAD_UNCHANGED)
    if img.ndim == 3 and img.shape[2] == 4:
        a = img[:, :, 3:4] / 255.0
        img = (img[:, :, :3] * a + 128 * (1 - a)).astype(np.uint8)
    box = cb.get("box") or find_bar(img[:, :, ::-1])
    idx = np.linspace(0, len(colors) - 1, min(48, len(colors))).astype(int)
    return {"box": [int(v) for v in box], "width": int(img.shape[1]), "height": int(img.shape[0]),
            "stops": [{"value": float(values[i]), "color": "#%02x%02x%02x" % tuple(int(c) for c in colors[i])} for i in idx],
            "min": float(values.min()), "max": float(values.max())}


def lut_for(tid, s):
    cb = colorbar_spec(tid, s)
    key = json.dumps([cb, s.get("color_space"), s.get("max_color_distance"), Path(cb["image"]).stat().st_mtime],
                     sort_keys=True, default=str)
    with LUT_LOCK:                    # built once (takes a couple of seconds); other requests wait for it
        if key not in LUT_CACHE:
            try:
                colors, values = read_colorbar(cb, ROOT)
            except SystemExit as e:
                raise Problem(str(e))
            LUT_CACHE.clear()
            LUT_CACHE[key] = build_lut(colors, values, float(s.get("max_color_distance") or 40), s.get("color_space") or "rgb")
        return LUT_CACHE[key]


def read_values(tid, s, frame):
    lut_v, lut_ok = lut_for(tid, s)
    q = (frame >> (8 - LUT_BITS)).astype(np.int32)
    key = (q[..., 0] << (2 * LUT_BITS)) | (q[..., 1] << LUT_BITS) | q[..., 2]
    val, matched = lut_v[key], lut_ok[key]
    ok = matched.copy()
    um = s.get("unmatched_value")
    if um not in (None, ""):
        val = np.where(matched, val, float(um))
        ok[:] = True
    return val, ok, matched


def ignored_mask(shape, s, x0=0, y0=0):
    m = np.zeros(shape[:2], bool)
    for a, b, c, d in s.get("ignore") or []:
        m[max(0, int(b) - y0):max(0, int(d) - y0), max(0, int(a) - x0):max(0, int(c) - x0)] = True
    return m


def probe(tid, body):
    frame = read_frame(tid, body.get("frame", 0))
    x, y = int(body["x"]), int(body["y"])
    if not (0 <= x < frame.shape[1] and 0 <= y < frame.shape[0]):
        raise Problem("outside the frame")
    val, ok, matched = read_values(tid, body["settings"], frame[y:y + 1, x:x + 1])
    ign = ignored_mask((1, 1), body["settings"], x, y)[0, 0]
    return {"rgb": [int(c) for c in frame[y, x]], "matched": bool(matched[0, 0]), "ignored": bool(ign),
            "used": bool(ok[0, 0] and not ign), "value": float(val[0, 0])}


def value_map(tid, body):
    frame = read_frame(tid, body.get("frame", 0))
    val, ok, _ = read_values(tid, body["settings"], frame)
    ok &= ~ignored_mask(frame.shape, body["settings"])
    cb = colorbar_spec(tid, body["settings"])
    lo, hi = float(cb["min"]), float(cb["max"])
    v01 = np.clip((val - lo) / ((hi - lo) or 1), 0, 1)
    vis = cv2.applyColorMap((v01 * 255).astype(np.uint8), cv2.COLORMAP_TURBO)[:, :, ::-1]
    vis[~ok] = (frame[~ok] * 0.25).astype(np.uint8)
    return png(vis)


# ---------------------------------------------------------------- saving

TRACK_KEYS = [k for k in KNOWN if k not in ("layers", "color_match", "min_background_diff", "heavy_threshold")]


def save_track(tid, body):
    is_new = bool(body.get("new"))
    folder = TRACKS_DIR / check_id(tid)
    if is_new and (folder / "track.toml").exists():
        raise Problem(f"A track called '{tid}' already exists. Pick another name.", 409)
    if not is_new and not (folder / "track.toml").exists():
        raise Problem(f"There's no track called '{tid}'.", 404)
    t = body.get("track") or {}
    if not str(t.get("title", "")).strip():
        raise Problem("Give the track a title.")
    old = tomllib.loads((folder / "track.toml").read_text(encoding="utf-8")) if not is_new else {}
    if old.get("kind", "field") != "field":
        raise Problem("This track type can't be edited in the studio yet: edit its .toml files instead.")

    clean = {}
    for k in TRACK_KEYS:
        if k in t and t[k] not in ("", None) and k != "kind":
            clean[k] = t[k]
    clean["kind"] = "field"
    for k in ("hours_per_frame", "slow_down", "max_color_distance", "unmatched_value",
              "hot_threshold", "cold_threshold", "very_cold_threshold"):
        if k in clean:
            clean[k] = float(clean[k])
    clean["ignore"] = [[int(round(v)) for v in box] for box in t.get("ignore") or []]
    clean["listening_guide"] = [line.strip() for line in t.get("listening_guide") or [] if line.strip()]
    cb = dict(t.get("colorbar") or {})
    cb = {k: v for k, v in cb.items() if v not in ("", None)}
    for k in ("min", "max", "ignore_above", "ignore_below"):
        if k in cb:
            cb[k] = float(cb[k])
    cb.setdefault("image", "colorbar.png")
    clean["colorbar"] = cb
    clean.setdefault("map", {"lon_min": -180, "lon_max": 180, "lat_max": 90, "lat_min": -90})
    for k in ("start_time", "hours_per_frame", "hot_threshold", "cold_threshold", "very_cold_threshold"):
        if k not in clean:
            raise Problem({"start_time": "Fill in the date and time of the first frame.",
                           "hours_per_frame": "Fill in the hours per frame."}.get(
                k, "Fill in the thresholds (high, low, very low)."))
    try:
        datetime.fromisoformat(clean["start_time"])
    except ValueError:
        raise Problem("The start time should look like 2026-10-30T09:00.")

    s = body.get("sounds") or {}
    snd = {"music": {**FIELD_GLOBAL["music"], **(s.get("music") or {})},
           "mix": {**FIELD_GLOBAL["mix"], **(s.get("mix") or {})},
           "sounds": []}
    for i, x in enumerate(s.get("sounds") or [], 1):
        kind = x.get("kind")
        if kind not in SOUND_DEFAULTS:
            raise Problem(f"Sound #{i} has no valid kind.")
        keep = {k: v for k, v in x.items() if k in SOUND_DEFAULTS[kind] or k == "kind"}
        for k in ("range", "pitch_range"):
            if k in keep:
                keep[k] = [None if v in ("", None) else float(v) for v in (keep[k] or [])]
                if not any(v is not None for v in keep[k]):
                    keep[k] = []
        snd["sounds"].append(keep)

    folder.mkdir(parents=True, exist_ok=True)
    clean["id"] = tid
    (folder / "track.toml").write_text(track_toml(clean), encoding="utf-8", newline="\n")
    (folder / "sounds.toml").write_text(sounds_toml(snd, clean["title"]), encoding="utf-8", newline="\n")
    # check it loads the way the engine reads it
    try:
        p = load_track(tid)
        load_sounds(folder / "sounds.toml", "field", folder, p)
    except SystemExit as e:
        raise Problem(f"Saved, but there's a problem: {e}")
    return {"ok": True, "id": tid}


def upload(tid, what, name, data):
    folder = TRACKS_DIR / check_id(tid)
    folder.mkdir(parents=True, exist_ok=True)      # a new track: its folder starts with the uploads
    if not data:
        raise Problem("The file is empty.")
    if what == "video":
        ext = Path(name or "video.mp4").suffix.lower()
        if ext not in VIDEO_TYPES:
            raise Problem(f"Upload an MP4 (or {', '.join(VIDEO_TYPES)}).")
        for old in folder.iterdir():
            if old.suffix.lower() in VIDEO_TYPES:
                old.unlink()
        (folder / f"video{ext}").write_bytes(data)
        return {"ok": True, "file": f"video{ext}"}
    if what == "colorbar":
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
        if img is None:
            raise Problem("That doesn't look like an image (use PNG or JPG).")
        cv2.imwrite(str(folder / "colorbar.png"), img)
        return {"ok": True, "file": "colorbar.png"}
    if what == "sample":
        fname = safe_name(name, "sample.wav")
        if not fname.lower().endswith(".wav"):
            raise Problem("Samples must be WAV files (convert MP3s first, e.g. with ffmpeg).")
        (folder / "samples").mkdir(exist_ok=True)
        path = folder / "samples" / fname
        path.write_bytes(data)
        try:
            load_sample(path, [folder])
        except SystemExit as e:
            path.unlink()
            raise Problem(str(e))
        return {"ok": True, "file": f"samples/{fname}", "note": guess_note(path)}
    raise Problem("Unknown upload type.")


def guess_note(path):
    """Rough pitch of a sample: the strongest tone, as a note name (e.g. 'D3')."""
    try:
        x = load_sample(path, [ROOT])
        seg = x[: synth.SAMPLE_RATE * 2]
        spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), 1 << 17))
        f = np.fft.rfftfreq(1 << 17, 1 / synth.SAMPLE_RATE)
        band = (f > 50) & (f < 2500)
        hz = f[band][spec[band].argmax()]
        midi = int(round(69 + 12 * np.log2(hz / 440)))
        return synth.NOTE_NAMES[midi % 12] + str(midi // 12 - 1)
    except Exception:
        return ""


# ---------------------------------------------------------------- builds

def start_build(tid, body):
    folder_of(tid)
    mode = body.get("mode", "preview")
    cmd = [sys.executable, "-u", str(ROOT / "sonify.py"), tid]
    if mode == "preview":
        cmd += ["--no-publish"]
        only = [n for n in body.get("only") or [] if n]
        if only:
            cmd += ["--only", ",".join(only)]
    job = {"id": uuid.uuid4().hex[:10], "track": tid, "mode": mode, "log": [], "done": False, "ok": None,
           "step": "Starting...", "started": time.time()}
    with JOBS_LOCK:
        JOBS[job["id"]] = job

    def run():
        try:
            proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace",
                                    env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
            for line in proc.stdout:
                line = line.rstrip()
                if not line or line.strip().startswith("frame "):
                    continue
                job["log"].append(line)
                if re.match(r"^\d/5 ", line):
                    job["step"] = line
            job["ok"] = proc.wait() == 0
        except Exception as e:
            job["log"].append(f"Error: {e}")
            job["ok"] = False
        job["done"] = True
        stamp = int(time.time())
        job["files"] = {k: f"/output/{tid}/{f}?t={stamp}" for k, f in
                        [("audio", "sonification.wav"), ("graph", "features.png"), ("captions", "descriptions.vtt")]
                        if (OUT / tid / f).exists()}

    threading.Thread(target=run, daemon=True).start()
    return {"job": job["id"]}


def job_status(jid):
    job = JOBS.get(jid)
    if not job:
        raise Problem("Unknown job.", 404)
    return {k: v for k, v in job.items()}


# ---------------------------------------------------------------- export / import / delete

def export_zip(tid, with_video=False):
    folder = folder_of(tid)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(folder.rglob("*")):
            if p.is_dir() or (p.suffix.lower() in VIDEO_TYPES and not with_video):
                continue
            z.write(p, f"{tid}/{p.relative_to(folder).as_posix()}")
    return buf.getvalue()


def import_zip(data, name=None, overwrite=False):
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise Problem("That isn't a zip file.")
    tomls = [n for n in z.namelist() if n.endswith("track.toml") and n.count("/") <= 1]
    if not tomls:
        raise Problem("No track.toml in the zip: export a track from the studio to get the right format.")
    prefix = tomls[0][: -len("track.toml")]
    tid = check_id(name or prefix.strip("/") or "imported")
    dest = TRACKS_DIR / tid
    if dest.exists() and not overwrite:
        raise Problem(f"A track called '{tid}' already exists.", 409)
    tmp = TRACKS_DIR / f"_import_{uuid.uuid4().hex[:6]}"
    tmp.mkdir(parents=True)
    try:
        for n in z.namelist():
            if not n.startswith(prefix) or n.endswith("/"):
                continue
            rel = Path(n[len(prefix):])
            target = (tmp / rel).resolve()
            if tmp.resolve() not in target.parents:          # no ../ tricks
                raise Problem("The zip contains an unsafe path.")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(n))
        tomllib.loads((tmp / "track.toml").read_text(encoding="utf-8"))
        if dest.exists():
            delete_track(tid)
        tmp.rename(dest)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
    return {"ok": True, "id": tid}


def delete_track(tid):
    folder = folder_of(tid)
    bin_ = TRACKS_DIR / "_deleted" / f"{tid}-{datetime.now():%Y%m%d-%H%M%S}"
    bin_.mkdir(parents=True)
    shutil.move(str(folder), str(bin_ / "track"))
    for f in (WEB / "media").glob(f"{tid}.*"):
        shutil.move(str(f), str(bin_ / f.name))
    tj = WEB / "tracks.json"
    if tj.exists():
        tracks = [t for t in json.loads(tj.read_text(encoding="utf-8")) if t.get("id") != tid]
        tj.write_text(json.dumps(tracks, indent=2), encoding="utf-8")
    return {"ok": True, "moved_to": str(bin_.relative_to(ROOT))}


# ---------------------------------------------------------------- the web server

class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if "/api/job/" not in self.path:
            sys.stderr.write("  %s\n" % (fmt % args))

    def translate_path(self, path):
        p = unquote(urlparse(path).path)
        for prefix, base in (("/studio", STUDIO), ("/output", OUT)):
            if p == prefix or p.startswith(prefix + "/"):
                rel = p[len(prefix):].lstrip("/") or "index.html"
                return str(self._inside(base, rel))
        return str(self._inside(WEB, p.lstrip("/") or "index.html"))

    @staticmethod
    def _inside(base, rel):
        target = (base / rel).resolve()
        return target if base.resolve() in target.parents or target == base.resolve() else base / "index.html"

    def end_headers(self):
        if self.path.startswith(("/api/", "/output/", "/studio/")) or self.path.endswith("tracks.json"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, obj, status=200):
        data = json.dumps(jsonable(obj)).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_bytes(self, data, ctype, filename=None):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def api(self, method):
        u = urlparse(self.path)
        parts = [unquote(p) for p in u.path.split("/")[2:]]
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if method == "GET":
                if parts == ["studio"]:
                    return self.send_json(studio_info())
                if parts[0] == "track" and len(parts) == 2:
                    return self.send_json(get_track(parts[1]))
                if parts[0] == "video" and len(parts) == 2:
                    return self.send_json(video_info(parts[1]))
                if parts[0] == "frame" and len(parts) == 2:
                    return self.send_bytes(png(read_frame(parts[1].removesuffix(".png"), int(q.get("i", 0)))), "image/png")
                if parts[0] == "colorbar-image" and len(parts) == 2:
                    path = any_folder(parts[1].removesuffix(".png")) / "colorbar.png"
                    if not path.exists():
                        raise Problem("No color bar yet.", 404)
                    return self.send_bytes(path.read_bytes(), "image/png")
                if parts[0] == "job" and len(parts) == 2:
                    return self.send_json(job_status(parts[1]))
                if parts[0] == "export" and len(parts) == 2:
                    tid = parts[1].removesuffix(".zip")
                    return self.send_bytes(export_zip(tid, q.get("video") == "1"), "application/zip", f"{tid}.zip")
            if method == "POST":
                raw = self.body()
                if parts[0] == "upload" and len(parts) == 3:
                    return self.send_json(upload(parts[1], parts[2], q.get("name"), raw))
                if parts[0] == "import":
                    return self.send_json(import_zip(raw, q.get("name") or None, q.get("overwrite") == "1"))
                body = json.loads(raw or b"{}")
                if parts[0] == "track" and len(parts) == 2:
                    return self.send_json(save_track(parts[1], body))
                if parts[0] == "colorbar" and len(parts) == 2:
                    return self.send_json(colorbar_info(parts[1], body))
                if parts[0] == "probe" and len(parts) == 2:
                    return self.send_json(probe(parts[1], body))
                if parts[0] == "valuemap" and len(parts) == 2:
                    return self.send_bytes(value_map(parts[1], body), "image/png")
                if parts[0] == "build" and len(parts) == 2:
                    return self.send_json(start_build(parts[1], body))
            if method == "DELETE" and parts[0] == "track" and len(parts) == 2:
                return self.send_json(delete_track(parts[1]))
            raise Problem("Not found.", 404)
        except Problem as e:
            return self.send_json({"error": str(e)}, e.status)
        except SystemExit as e:
            return self.send_json({"error": str(e)}, 400)
        except Exception as e:
            traceback.print_exc()
            return self.send_json({"error": f"Something went wrong: {e}"}, 500)

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self.api("GET")
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/"):
            return self.api("POST")
        self.send_error(405)

    def do_DELETE(self):
        if self.path.startswith("/api/"):
            return self.api("DELETE")
        self.send_error(405)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
            return                    # the browser stopped a download (e.g. left the page): not a problem
        super().handle_error(request, client_address)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    # Windows sometimes has wrong types in its registry (e.g. .js as text/plain), which breaks pages
    for ctype, ext in [("text/javascript", ".js"), ("text/javascript", ".mjs"), ("text/css", ".css"), ("text/html", ".html"),
                       ("application/json", ".json"), ("text/vtt", ".vtt"), ("video/mp4", ".mp4"), ("audio/wav", ".wav"),
                       ("image/png", ".png"), ("image/svg+xml", ".svg")]:
        mimetypes.add_type(ctype, ext)
    Handler.extensions_map = {**Handler.extensions_map, ".js": "text/javascript", ".css": "text/css", ".vtt": "text/vtt"}
    server = Server(("127.0.0.1", args.port), Handler)
    print(f"Earth Jukebox studio running.\n  Website: http://localhost:{args.port}\n"
          f"  Studio:  http://localhost:{args.port}/studio/\nPress Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
