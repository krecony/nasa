"""The studio's logic: reading, checking and saving tracks, colors, uploads, export/import.

Shared by the local studio (studio.py, a small web server) and the browser version on the
public website (jukebox/web.py, run by Pyodide). Both answer the same requests with route();
the few things that work differently there (where the video comes from, how a build runs,
what Delete does) are in HOOKS.
"""

import io
import json
import re
import shutil
import threading
import tomllib
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

import cv2
import numpy as np

from . import synth
from .colorbar import find_bar, read_colorbar
from .config import FIELD_GLOBAL, SOUND_DEFAULTS, load_sounds
from .field import LUT_BITS, build_lut
from .instruments import BUILTIN_NOTES, TEXTURES, load_sample
from .tomlwriter import SOUND_HELP, sounds_toml, track_toml
from .tracks import KNOWN, ROOT, TRACKS_DIR, VIDEO_TYPES, all_track_names, find_video, load_track

WEB, OUT = ROOT / "website", ROOT / "output"
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,40}$")
FILE_RE = re.compile(r"[^A-Za-z0-9._#-]+")
LUT_CACHE, LUT_LOCK = {}, threading.Lock()
EXPORT_SKIP = {"analysis.pkl", "video.json"}     # browser-only helper files, not part of a track


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
                item["video"] = HOOKS.video_name(t["folder"], t)
            except (SystemExit, Problem):
                item["video"] = None
        except SystemExit as e:
            item.update(title=name, error=str(e), editable=False)
        tracks.append(item)
    return {
        "tracks": tracks,
        "shared_samples": HOOKS.shared_samples(), "mode": HOOKS.mode,
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
        out["video"] = HOOKS.video_name(folder, t)
    except (SystemExit, Problem) as e:
        out["video"], out["video_problem"] = None, str(e)
    if t["kind"] == "field" and (folder / "sounds.toml").exists():
        snd = load_sounds(folder / "sounds.toml", "field", folder, t)
        out["sounds"] = {"music": snd["music"], "mix": snd["mix"], "sounds": snd["sounds"]}
    return jsonable(out)


def video_info(tid):
    return HOOKS.video_info(tid)


def read_frame(tid, index=0):
    """RGB frame of the track's video."""
    return HOOKS.read_frame(tid, index)


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
        return HOOKS.save_video(tid, folder, name, data)
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


# ---------------------------------------------------------------- export / import / delete

def export_zip(tid, with_video=False):
    folder = folder_of(tid)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(folder.rglob("*")):
            if p.is_dir() or (p.suffix.lower() in VIDEO_TYPES and not with_video) or p.name in EXPORT_SKIP:
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
    folder_of(tid)
    return HOOKS.delete(tid)


# ---------------------------------------------------------------- what differs between the server and the browser

class FileHooks:
    """Video files on disk (the local studio and the command line)."""
    mode = "server"

    def video_name(self, folder, cfg):
        return find_video(folder, cfg).name

    def _video_path(self, tid):
        folder = any_folder(tid)
        try:
            return find_video(folder, raw_cfg(folder))
        except SystemExit as e:
            raise Problem(str(e))

    def video_info(self, tid):
        path = self._video_path(tid)
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            raise Problem(f"Can't open the video {path.name}.")
        info = {"name": path.name, "fps": cap.get(cv2.CAP_PROP_FPS),
                "frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
                "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}
        cap.release()
        info["seconds"] = info["frames"] / info["fps"] if info["fps"] else 0
        return info

    def read_frame(self, tid, index):
        cap = cv2.VideoCapture(str(self._video_path(tid)))
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, min(int(index), total - 1)))
        ok, frame = cap.read()
        cap.release()
        if not ok:
            raise Problem("Couldn't read a frame from the video.")
        return frame[:, :, ::-1]

    def save_video(self, tid, folder, name, data):
        ext = Path(name or "video.mp4").suffix.lower()
        if ext not in VIDEO_TYPES:
            raise Problem(f"Upload an MP4 (or {', '.join(VIDEO_TYPES)}).")
        for old in folder.iterdir():
            if old.suffix.lower() in VIDEO_TYPES:
                old.unlink()
        (folder / f"video{ext}").write_bytes(data)
        forget_video_name(folder)
        return {"ok": True, "file": f"video{ext}"}

    def shared_samples(self):
        return sorted(f"samples/{p.name}" for p in (ROOT / "samples").glob("*.wav"))

    def build(self, tid, body):
        raise Problem("Building isn't available here.")

    def job(self, jid):
        raise Problem("Unknown job.", 404)

    def delete(self, tid):
        """Move the folder to tracks/_deleted/ (so it can be brought back) and take it off the website."""
        folder = TRACKS_DIR / tid
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


def forget_video_name(folder):
    """A new video was uploaded: track.toml shouldn't point at another file name any more."""
    tf = folder / "track.toml"
    if tf.exists():
        text = tf.read_text(encoding="utf-8")
        new = re.sub(r'(?m)^video\s*=\s*"[^"\n]*"', 'video = ""', text)
        if new != text:
            tf.write_text(new, encoding="utf-8", newline="\n")


HOOKS = FileHooks()


# ---------------------------------------------------------------- one entry point for every request

def route(method, path, query=None, body=b""):
    """Answer one studio request: ("GET", "/api/track/WindSpeed", {"i": "3"}, b"...").
    Returns (status, content_type, data_bytes, download_filename_or_None)."""
    q = query or {}
    parts = [unquote(p) for p in path.split("?")[0].strip("/").split("/")]
    if parts and parts[0] == "api":
        parts = parts[1:]
    parts = parts or [""]
    ok = lambda obj: (200, "application/json", json.dumps(jsonable(obj)).encode(), None)
    try:
        if method == "GET":
            if parts == ["studio"]:
                return ok(studio_info())
            if parts[0] == "track" and len(parts) == 2:
                return ok(get_track(parts[1]))
            if parts[0] == "video" and len(parts) == 2:
                return ok(video_info(parts[1]))
            if parts[0] == "frame" and len(parts) == 2:
                return 200, "image/png", png(read_frame(parts[1].removesuffix(".png"), int(q.get("i", 0)))), None
            if parts[0] == "colorbar-image" and len(parts) == 2:
                img = any_folder(parts[1].removesuffix(".png")) / "colorbar.png"
                if not img.exists():
                    raise Problem("No color bar yet.", 404)
                return 200, "image/png", img.read_bytes(), None
            if parts[0] == "job" and len(parts) == 2:
                return ok(HOOKS.job(parts[1]))
            if parts[0] == "export" and len(parts) == 2:
                tid = parts[1].removesuffix(".zip")
                return 200, "application/zip", export_zip(tid, q.get("video") == "1"), f"{tid}.zip"
        if method == "POST":
            if parts[0] == "upload" and len(parts) == 3:
                return ok(upload(parts[1], parts[2], q.get("name"), body))
            if parts[0] == "import":
                return ok(import_zip(body, q.get("name") or None, q.get("overwrite") == "1"))
            data = json.loads(body or b"{}")
            if parts[0] == "track" and len(parts) == 2:
                return ok(save_track(parts[1], data))
            if parts[0] == "colorbar" and len(parts) == 2:
                return ok(colorbar_info(parts[1], data))
            if parts[0] == "probe" and len(parts) == 2:
                return ok(probe(parts[1], data))
            if parts[0] == "valuemap" and len(parts) == 2:
                return 200, "image/png", value_map(parts[1], data), None
            if parts[0] == "build" and len(parts) == 2:
                folder_of(parts[1])
                return ok(HOOKS.build(parts[1], data))
        if method == "DELETE" and parts[0] == "track" and len(parts) == 2:
            return ok(delete_track(parts[1]))
        raise Problem("Not found.", 404)
    except Problem as e:
        return e.status, "application/json", json.dumps({"error": str(e)}).encode(), None
    except SystemExit as e:
        return 400, "application/json", json.dumps({"error": str(e)}).encode(), None
