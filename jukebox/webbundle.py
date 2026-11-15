"""Packs the jukebox Python code into website/py/jukebox.zip for the public "add your own" page.

The browser (Pyodide) downloads this zip and runs the same code as `py sonify.py`.
It's rebuilt automatically by `py studio.py` and `py sonify.py` when the code changed (and by
the GitHub Pages workflow). The zip is byte-for-byte the same when the code is the same, on
every computer: files are stored uncompressed, because compression libraries differ between
computers. So git only sees a change when the Python code really changed.
"""

import io
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "website" / "py" / "jukebox.zip"
SKIP = {"plots.py"}            # needs matplotlib; the browser version doesn't draw the graph


def bundle_bytes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for p in sorted((ROOT / "jukebox").glob("*.py")):
            if p.name in SKIP:
                continue
            info = zipfile.ZipInfo(f"jukebox/{p.name}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o644 << 16
            # same line endings on every computer (git on Windows may check files out with CRLF)
            z.writestr(info, p.read_bytes().replace(b"\r\n", b"\n"))
    return buf.getvalue()


def make_bundle():
    """Write the zip if the code changed. Returns True when it was (re)written."""
    data = bundle_bytes()
    if BUNDLE.exists() and BUNDLE.read_bytes() == data:
        return False
    BUNDLE.parent.mkdir(parents=True, exist_ok=True)
    BUNDLE.write_bytes(data)
    return True


if __name__ == "__main__":
    print("updated" if make_bundle() else "already up to date", BUNDLE)
