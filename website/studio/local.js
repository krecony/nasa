/* The studio without a server (the public website): the same form, with Python running in this
   browser (py-worker.js -> jukebox/web.py) and everything saved only in this browser.

   LocalStudio.api(path, options) answers the same requests as `py studio.py` (/api/...):
   most go straight to Python; the browser does the video parts itself, because Python in the
   browser can't decode MP4s: it keeps the video file, reads frames with a <video> element and
   sends them to Python. */
"use strict";

window.LocalStudio = (() => {
  const COMMON_FPS = [10, 12, 15, 23.976, 24, 25, 29.97, 30, 48, 50, 59.94, 60];
  let worker = null, seq = 0, Mine = null, onProgress = () => {};
  const waiting = new Map();
  const jobs = new Map();
  const videos = new Map();         // track id -> { el, url } (the <video> used to read frames)
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  /* ------------------------------------------------ talking to Python */

  function call(fn, args = [], transfer = []) {
    return new Promise((resolve, reject) => {
      const id = ++seq;
      waiting.set(id, { resolve, reject });
      worker.postMessage({ id, fn, args }, transfer);
    });
  }

  async function start(progress) {
    onProgress = progress || onProgress;
    Mine = await import("../js/mytracks.js");
    Mine.keepStorage();
    worker = new Worker(window.EJ_WORKER_URL || "py-worker.js");
    worker.onmessage = (e) => {
      const m = e.data;
      if (m.progress) return onProgress(m.progress);
      const w = waiting.get(m.id); if (!w) return;
      waiting.delete(m.id);
      m.ok ? w.resolve(m.result) : w.reject(Object.assign(new Error(m.error), { status: 400 }));
    };
    worker.onerror = (e) => onProgress("Python couldn't start: " + (e.message || "unknown error"));
    await call("init", [new URL("../py/jukebox.zip", location.href).href]);
  }

  async function toBytes(body) {
    if (body === undefined || body === null) return null;
    if (typeof body === "string") return new TextEncoder().encode(body);
    if (body instanceof Blob) return new Uint8Array(await body.arrayBuffer());
    if (body instanceof ArrayBuffer) return new Uint8Array(body);
    return body;
  }

  async function python(method, path, query, body) {
    const bytes = await toBytes(body);
    const r = await call("handle", [method, "/api/" + path, JSON.stringify(query || {}), bytes], bytes ? [bytes.buffer] : []);
    const isJson = r.ctype.includes("json");
    const data = isJson ? JSON.parse(new TextDecoder().decode(r.data)) : new Blob([r.data], { type: r.ctype });
    if (r.status >= 400) throw Object.assign(new Error(data.error || "Something went wrong."), { status: r.status });
    return data;
  }

  /* ------------------------------------------------ the video, read by the browser */

  async function videoFor(id) {
    const have = videos.get(id);
    if (have) return have.el;
    const blob = await Mine.getMedia(`${id}/video`);
    if (!blob) throw Object.assign(new Error("Upload the video first (section 2)."), { status: 404 });
    return openVideo(id, blob);
  }

  function openVideo(id, blob) {
    forget(id);
    const el = document.createElement("video");
    el.muted = true; el.playsInline = true; el.preload = "auto";
    // in the page (tiny and see-through): browsers only report frames of videos that are on the page
    el.style.cssText = "position:fixed;right:0;bottom:0;width:2px;height:2px;opacity:0.01;pointer-events:none;";
    el.setAttribute("aria-hidden", "true");
    document.body.append(el);
    const url = URL.createObjectURL(blob);
    el.src = url;
    videos.set(id, { el, url });
    return new Promise((resolve, reject) => {
      el.addEventListener("loadeddata", () => resolve(el), { once: true });
      el.addEventListener("error", () => { forget(id);
        reject(new Error("This browser can't play that video. Use an MP4 (H.264), like the NASA downloads.")); }, { once: true });
    });
  }

  function forget(id) {
    const v = videos.get(id);
    if (v) { v.el.remove(); URL.revokeObjectURL(v.url); videos.delete(id); }
  }

  function seekTo(v, t) {
    return new Promise((resolve) => {
      if (Math.abs(v.currentTime - t) < 1e-6 && v.readyState >= 2) return resolve();
      v.addEventListener("seeked", () => resolve(), { once: true });
      v.currentTime = t;
    });
  }

  async function detectFps(v) {
    if (!("requestVideoFrameCallback" in v)) return null;
    const times = [];
    await new Promise((resolve) => {
      let done = false;
      const stop = () => { if (!done) { done = true; resolve(); } };
      const cb = (_, meta) => { times.push(meta.mediaTime); if (times.length >= 14) stop(); else v.requestVideoFrameCallback(cb); };
      v.requestVideoFrameCallback(cb);
      v.play().catch(stop);
      setTimeout(stop, 4000);
    });
    v.pause();
    await seekTo(v, 0);
    const steps = times.slice(1).map((t, i) => t - times[i]).filter((d) => d > 1e-4);
    if (!steps.length) return null;
    const fps = 1 / Math.min(...steps);
    return COMMON_FPS.find((f) => Math.abs(f - fps) / f < 0.02) || +fps.toFixed(3);
  }

  async function uploadVideo(id, file, name) {
    if (!file || !file.size) throw new Error("The file is empty.");
    if (file.size > 1.5e9) throw new Error("That video is too big for the browser (over 1.5 GB).");
    const el = await openVideo(id, file);
    const fps = (await detectFps(el)) || 30;
    const info = { name: name || file.name || "video.mp4", fps, width: el.videoWidth, height: el.videoHeight,
                   seconds: el.duration, frames: Math.max(2, Math.round(el.duration * fps)), fps_detected: fps };
    await Mine.putMedia(`${id}/video`, file);
    await call("set_video", [id, JSON.stringify(info)]);
    return { ok: true, file: info.name };
  }

  async function setFps(id, fps) {
    const info = await python("GET", `video/${id}`);
    info.fps = +fps;
    info.frames = Math.max(2, Math.round(info.seconds * info.fps));
    await call("set_video", [id, JSON.stringify(info)]);
    return info;
  }

  function canvas(w, h) {
    const c = document.createElement("canvas");
    c.width = w; c.height = h;
    const ctx = c.getContext("2d", { willReadFrequently: true });
    ctx.imageSmoothingEnabled = false;          // nearest pixel, like OpenCV's INTER_NEAREST: no blended colors
    return [c, ctx];
  }

  async function frameImage(id, index) {
    const info = await python("GET", `video/${id}`);
    const v = await videoFor(id);
    const i = Math.max(0, Math.min(info.frames - 1, index | 0));
    await seekTo(v, (i + 0.5) / info.fps);
    const [c, ctx] = canvas(v.videoWidth, v.videoHeight);
    ctx.drawImage(v, 0, 0);
    const png = await new Promise((r) => c.toBlob(r, "image/png"));
    const rgba = new Uint8Array(ctx.getImageData(0, 0, c.width, c.height).data.buffer);
    await call("set_frame", [id, i, rgba, c.width, c.height], [rgba.buffer]);   // for the color check and value map
    return png;
  }

  /* Every frame, in order, at the analysis size. Plays the video and takes each frame as it's shown
     (fast); when a frame is skipped it seeks back for it; it pauses while Python catches up. */
  async function captureFrames(v, fps, n, W, H, deliver, onCount) {
    const [, ctx] = canvas(W, H);
    const grab = () => { ctx.drawImage(v, 0, 0, W, H); return new Uint8Array(ctx.getImageData(0, 0, W, H).data.buffer); };
    let next = 0, inflight = 0, failed = null;
    let useCallbacks = "requestVideoFrameCallback" in v;
    const send = (rgba) => {
      const i = next++;
      inflight++;
      deliver(i, rgba).then(() => { inflight--; }, (e) => { failed = failed || e; inflight--; });
      onCount(next);
    };
    const drain = async (max) => { while (inflight > max && !failed) await sleep(10); if (failed) throw failed; };

    v.pause();
    let needSeek = true;
    while (next < n) {
      if (needSeek) {
        await seekTo(v, (next + 0.5) / fps);
        send(grab());
        needSeek = false;
      }
      if (!useCallbacks) { needSeek = true; await drain(2); continue; }
      const why = await new Promise((resolve) => {
        let stopped = false, seen = false;
        const stop = (reason) => { if (!stopped) { stopped = true; v.pause(); resolve(reason); } };
        const cb = (_, meta) => {
          if (stopped) return;
          seen = true;
          const i = Math.round(meta.mediaTime * fps);
          if (i === next) send(grab());
          else if (i > next) return stop("skipped");
          if (next >= n || failed) return stop("done");
          if (inflight >= 4) return stop("busy");
          v.requestVideoFrameCallback(cb);
        };
        v.requestVideoFrameCallback(cb);
        v.addEventListener("ended", () => stop("ended"), { once: true });
        setTimeout(() => { if (!stopped && !seen) { useCallbacks = false; stop("no-callbacks"); } }, 3000);
        v.play().catch(() => { useCallbacks = false; stop("no-play"); });
      });
      if (why === "busy") await drain(1);
      else if (why !== "done") needSeek = true;
    }
    await drain(0);
  }

  /* ------------------------------------------------ builds */

  function startBuild(id, body) {
    const job = { id: "web" + (++seq), step: "Getting ready…", log: [], done: false, ok: null, files: {} };
    jobs.set(job.id, job);
    (async () => {
      try {
        const mode = body.mode === "publish" ? "publish" : "preview";
        const b = JSON.parse(await call("begin", [id, mode, JSON.stringify(body.only || [])]));
        if (b.need_frames) {
          const v = await videoFor(id);
          const [W, H] = b.work;
          const t0 = Date.now();
          await captureFrames(v, b.fps, b.frames, W, H,
            (i, rgba) => call("add_frame", [b.job, rgba, W, H], [rgba.buffer]),
            (k) => { job.step = `Reading the video: frame ${k} of ${b.frames}`; });
          job.log.push(`Read ${b.frames} frames in ${((Date.now() - t0) / 1000).toFixed(0)} s.`);
        } else {
          job.log.push("Using the saved video analysis (the video and color settings didn't change).");
        }
        job.step = "Making the soundtrack…";
        const r = await call("finish", [b.job]);
        const d = JSON.parse(r.details);
        job.log.push(...d.log);
        const wav = new Blob([r.wav], { type: "audio/wav" });
        job.files.audio = URL.createObjectURL(wav);
        if (mode === "publish") {
          await Mine.putMedia(`${id}/audio`, wav);
          await Mine.putMedia(`${id}/captions`, new Blob([d.captions_video], { type: "text/vtt" }));
          await Mine.putTrack({ id, title: d.title, source: d.source, description: d.description,
            listening_guide: d.listening_guide, slow_down: d.slow_down, duration: d.duration, video_seconds: d.video_seconds });
          job.log.push("Saved to your jukebox (only in this browser).");
        }
        job.ok = true;
      } catch (e) {
        job.log.push("Error: " + e.message);
        job.ok = false;
      }
      job.done = true;
    })();
    return { job: job.id };
  }

  /* ------------------------------------------------ the requests the form makes */

  async function api(path, opts = {}) {
    const method = opts.method || "GET";
    const [p, qs] = path.split("?");
    const query = Object.fromEntries(new URLSearchParams(qs || ""));
    const parts = p.split("/").map(decodeURIComponent);
    if (method === "POST" && parts[0] === "upload" && parts[2] === "video") return uploadVideo(parts[1], opts.body, query.name);
    if (parts[0] === "frame") return frameImage(parts[1].replace(/\.png$/, ""), +query.i || 0);
    if (parts[0] === "build") return startBuild(parts[1], JSON.parse(opts.body || "{}"));
    if (parts[0] === "job") {
      const j = jobs.get(parts[1]);
      if (!j) throw Object.assign(new Error("Unknown job."), { status: 404 });
      return JSON.parse(JSON.stringify(j));
    }
    if (method === "DELETE" && parts[0] === "track") {
      const r = await python("DELETE", p, query);
      forget(parts[1]);
      await Mine.removeTrack(parts[1]);
      return r;
    }
    return python(method, p, query, opts.body);
  }

  return { start, api, setFps };
})();
