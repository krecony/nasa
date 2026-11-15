// Runs Python in the visitor's browser (Pyodide), in the background so the page stays responsive.
// It only passes requests to jukebox/web.py and gives back its answers (text and bytes).
// The track folders (tracks/) are kept in the browser's storage (IndexedDB) with Pyodide's IDBFS.

const PYODIDE = 'https://cdn.jsdelivr.net/pyodide/v0.27.7/full/';
importScripts(PYODIDE + 'pyodide.js');

let py = null;
let web = null;
let queue = Promise.resolve();          // one request at a time: Python runs one thing at a time anyway

const progress = (text) => self.postMessage({ progress: text });

function syncfs(populate) {
  return new Promise((resolve, reject) => py.FS.syncfs(populate, (err) => (err ? reject(err) : resolve())));
}

// Python bytes (a PyProxy) -> Uint8Array
function bytesOf(px) {
  if (px === undefined || px === null) return null;
  if (px instanceof Uint8Array) return px;
  try {
    if (typeof px.getBuffer === 'function') {
      const buf = px.getBuffer('u8');
      try { return buf.data.slice(); } finally { buf.release(); }
    }
    const js = px.toJs();
    return js instanceof Uint8Array ? js : new Uint8Array(js);
  } finally {
    px.destroy?.();
  }
}

// Python's error -> the last line, without the exception's module name ("...Problem: Fill in the title.")
function message(err) {
  const lines = String(err?.message || err).trim().split('\n');
  return lines[lines.length - 1].replace(/^[\w.]*(Problem|Error|Exception|SystemExit)\w*:\s*/, '') || 'Something went wrong.';
}

const calls = {
  async init(bundleUrl) {
    progress('Downloading Python (first time only, about 35 MB)…');
    py = await loadPyodide({ indexURL: PYODIDE });
    progress('Loading NumPy, SciPy and OpenCV…');
    await py.loadPackage(['numpy', 'scipy', 'opencv-python']);
    progress('Opening your saved tracks…');
    py.FS.mkdirTree('/ej/tracks');
    py.FS.mount(py.FS.filesystems.IDBFS, {}, '/ej/tracks');
    await syncfs(true);
    progress('Loading the jukebox code…');
    const res = await fetch(bundleUrl, { cache: 'no-cache' });
    if (!res.ok) throw new Error(`Couldn't download ${bundleUrl} (${res.status}).`);
    py.unpackArchive(await res.arrayBuffer(), 'zip', { extractDir: '/ej' });
    py.runPython("import sys\nif '/ej' not in sys.path: sys.path.insert(0, '/ej')");
    web = py.pyimport('jukebox.web');
    web.setup();
    return 'ready';
  },

  async handle(method, path, queryJson, body) {
    const t = web.handle(method, path, queryJson, body);
    try {
      const result = { status: t.get(0), ctype: t.get(1), data: bytesOf(t.get(2)), filename: t.get(3) ?? null };
      if (method !== 'GET') await syncfs(false);
      return result;
    } finally { t.destroy(); }
  },

  async set_video(id, infoJson) {
    const r = web.set_video(id, infoJson);
    await syncfs(false);
    return r;
  },

  set_frame: (id, index, rgba, w, h) => web.set_frame(id, index, rgba, w, h),
  begin: (id, mode, onlyJson) => web.begin(id, mode, onlyJson),
  add_frame: (job, rgba, w, h) => web.add_frame(job, rgba, w, h),

  async finish(job) {
    const t = web.finish(job);
    try {
      const result = { details: t.get(0), wav: bytesOf(t.get(1)) };
      await syncfs(false);               // the analysis is cached in the track folder
      return result;
    } finally { t.destroy(); }
  },
};

self.onmessage = (e) => {
  const { id, fn, args } = e.data;
  queue = queue.then(async () => {
    try {
      if (!calls[fn]) throw new Error(`Unknown call ${fn}`);
      if (fn !== 'init' && !web) throw new Error('Python is still loading.');
      const result = await calls[fn](...(args || []));
      const transfer = [result?.data?.buffer, result?.wav?.buffer].filter(Boolean);
      self.postMessage({ id, ok: true, result }, transfer);
    } catch (err) {
      console.error(err);
      self.postMessage({ id, ok: false, error: message(err) });
    }
  });
};
