"""Earth Jukebox studio: the website plus a form to add and edit tracks.

    py studio.py               then open http://localhost:8000
    py studio.py --port 8080   use another port

It serves the website exactly like `py -m http.server` (from the website folder) and adds:
    /studio/     the Add / Edit track form (website/studio/), saving into tracks/
    /api/...     what the form talks to (save, upload, build, export, import, delete)
    /output/...  preview files (soundtrack, graph, captions)

Everything stays on this computer: the server only listens to this computer (127.0.0.1).
On the public website the same form runs in the visitor's browser instead (see jukebox/web.py)
and saves only in their browser.
"""

import argparse
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from jukebox import studio_core as core
from jukebox.webbundle import make_bundle

ROOT = core.ROOT
WEB, OUT = core.WEB, core.OUT


class ServerHooks(core.FileHooks):
    """Builds run sonify.py in the background; the form asks for progress with /api/job/<id>."""

    def __init__(self):
        self.jobs, self.lock = {}, threading.Lock()

    def build(self, tid, body):
        mode = body.get("mode", "preview")
        cmd = [sys.executable, "-u", str(ROOT / "sonify.py"), tid, "--progress"]
        if mode == "preview":
            cmd += ["--no-publish"]
            only = [n for n in body.get("only") or [] if n]
            if only:
                cmd += ["--only", ",".join(only)]
        job = {"id": uuid.uuid4().hex[:10], "track": tid, "mode": mode, "log": [], "done": False, "ok": None,
               "step": "Starting...", "progress": None, "started": time.time()}
        with self.lock:
            self.jobs[job["id"]] = job

        def run():
            try:
                proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding="utf-8", errors="replace",
                                        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
                for line in proc.stdout:
                    line = line.rstrip()
                    m = re.match(r"\s*frame (\d+)/(\d+)", line)        # progress for the bar, not for the log
                    if m:
                        job["progress"] = [int(m[1]), int(m[2])]
                        continue
                    m = re.match(r"\s*video (\d+)%", line)
                    if m:
                        job["progress"] = [int(m[1]), 100]
                        continue
                    if not line:
                        continue
                    job["log"].append(line)
                    if re.match(r"^\d/5 ", line):
                        job["step"], job["progress"] = line, None
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

    def job(self, jid):
        job = self.jobs.get(jid)
        if not job:
            raise core.Problem("Unknown job.", 404)
        return dict(job)


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if "/api/job/" not in self.path:
            sys.stderr.write("  %s\n" % (fmt % args))

    def translate_path(self, path):
        p = unquote(urlparse(path).path)
        if p == "/output" or p.startswith("/output/"):
            return str(self._inside(OUT, p[len("/output"):].lstrip("/")))
        rel = p.lstrip("/")
        if not rel or rel.endswith("/"):
            rel += "index.html"
        return str(self._inside(WEB, rel))

    @staticmethod
    def _inside(base, rel):
        target = (base / rel).resolve()
        return target if base.resolve() in target.parents or target == base.resolve() else base / "index.html"

    def end_headers(self):
        if self.path.startswith(("/api/", "/output/", "/studio/", "/py/")) or self.path.endswith("tracks.json"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def api(self, method):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        try:
            status, ctype, data, filename = core.route(method, u.path, q, body)
        except Exception as e:
            traceback.print_exc()
            status, ctype, data, filename = 500, "application/json", json.dumps({"error": f"Something went wrong: {e}"}).encode(), None
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

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
                       ("image/png", ".png"), ("image/svg+xml", ".svg"), ("application/zip", ".zip")]:
        mimetypes.add_type(ctype, ext)
    Handler.extensions_map = {**Handler.extensions_map, ".js": "text/javascript", ".css": "text/css", ".vtt": "text/vtt"}
    core.HOOKS = ServerHooks()
    if make_bundle():
        print("Updated website/py/jukebox.zip (the Python code the public 'add your own' page runs).")
    server = Server(("127.0.0.1", args.port), Handler)
    print(f"Earth Jukebox studio running.\n  Website: http://localhost:{args.port}\n"
          f"  Studio:  http://localhost:{args.port}/studio/\nPress Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
