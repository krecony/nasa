/* Earth Jukebox studio: the Add / Edit track form.
   With `py studio.py` it talks to that server (/api/...) and saves into tracks/.
   On the public website there's no server: local.js runs the same Python in this browser
   and saves only in this browser. Plain JS, no build step. */
"use strict";

const $ = (s, root = document) => root.querySelector(s);
const ID_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,40}$/;
const OFFSETS = [[-10, "Hawaii"], [-8, "PST"], [-7, "PDT / MST"], [-6, "MDT / CST"], [-5, "CDT / EST"], [-4, "EDT"],
  [-3, ""], [0, "UTC / GMT"], [1, "CET / BST"], [2, "CEST / EET"], [3, "EEST / Moscow"], [5.5, "India"], [8, "China"], [9, "Japan"], [10, "AEST"]];
const SOUND_KINDS = {
  voices: "Voices: one held note per band of latitude; higher value = higher note",
  hits: "Hits: short notes where the value is inside a range (more area = more notes)",
  background: "Background: a sound that gets louder with the global average or with the area inside a range",
  chime: "Chime: rings at the start of every day",
};
const MAIN_KEYS = ["name", "enabled", "volume", "instrument", "texture", "sample", "root", "measure", "hemisphere", "note"];
const SELECTS = { measure: ["area", "mean"], hemisphere: ["all", "north", "south"], color_space: ["rgb", "lab"] };

let INFO = null;      // /api/studio
let T = null;         // the open track: { id, isNew, editable, track, sounds, video, cb, files }
let dirty = false;
const API = "../api/";            // the local studio's server (py studio.py)
let MODE = "server";              // "browser" on the public website (see local.js)
const inBrowser = () => MODE === "browser";

/* ---------------------------------------------------------------- small helpers */

function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v === true) e.setAttribute(k, "");
    else e.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k !== null && k !== undefined && k !== false) e.append(k.nodeType ? k : document.createTextNode(k));
  return e;
}

async function api(path, opts = {}) {
  if (inBrowser()) return LocalStudio.api(path, opts);
  const r = await fetch(API + path, opts);
  const ct = r.headers.get("content-type") || "";
  if (!r.ok) {
    const msg = ct.includes("json") ? (await r.json()).error : r.statusText;
    const err = new Error(msg || "Something went wrong."); err.status = r.status; throw err;
  }
  return ct.includes("json") ? r.json() : r.blob();
}
/* an <img> showing something from the studio (a URL on the server, a picture made here in the browser) */
async function setImg(img, path) {
  if (!inBrowser()) { img.src = API + path; return; }
  try {
    const blob = await api(path);
    if (img.dataset.url) URL.revokeObjectURL(img.dataset.url);
    img.src = img.dataset.url = URL.createObjectURL(blob);
  } catch (e) { fail(e); }
}
const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

let toastTimer;
function status(msg, kind = "") {
  const t = $("#status");
  t.className = "toast " + kind; t.textContent = msg;
  clearTimeout(toastTimer);
  if (kind !== "bad") toastTimer = setTimeout(() => { t.textContent = ""; }, 6000);
}
const fail = (e) => status(e.message || String(e), "bad");
const touch = () => { dirty = true; };
const num = (v) => (v === "" || v === null || v === undefined || isNaN(+v) ? null : +v);
const fmt = (v) => (v === null || v === undefined ? "" : String(+(+v).toFixed(4)));
let uid = 0; const nid = (p) => `${p}-${++uid}`;

/* labelled inputs bound to obj[key] */
function field(label, input, hint, cls) {
  return el("label", { class: "f " + (cls || "") }, label, input, hint ? el("span", { class: "hint" }, hint) : null);
}
function text(obj, key, attrs = {}) {
  return el("input", { type: "text", value: obj[key] ?? "", ...attrs, oninput: (e) => { obj[key] = e.target.value; touch(); attrs.onchange2?.(); } });
}
function number(obj, key, attrs = {}, after) {
  return el("input", { type: "number", step: "any", value: fmt(obj[key]), ...attrs,
    oninput: (e) => { obj[key] = num(e.target.value); touch(); after?.(); } });
}
function check(obj, key, label, after) {
  const c = el("input", { type: "checkbox", onchange: (e) => { obj[key] = e.target.checked; touch(); after?.(); } });
  c.checked = !!obj[key];
  return el("label", { class: "check" }, c, label);
}
function select(obj, key, options, after) {
  const cur = obj[key];
  if (cur !== undefined && cur !== null && cur !== "" && !options.some((o) => String(Array.isArray(o) ? o[0] : o) === String(cur)))
    options = [...options, cur];          // keep a value the list doesn't know (e.g. typed in the .toml)
  const s = el("select", { onchange: (e) => { obj[key] = e.target.value; touch(); after?.(e.target.value); } },
    options.map((o) => { const [v, l] = Array.isArray(o) ? o : [o, o]; return el("option", { value: v, selected: String(obj[key]) === String(v) }, l); }));
  return s;
}
function lines(obj, key, attrs = {}) {
  const t = el("textarea", { ...attrs, oninput: (e) => { obj[key] = e.target.value.split("\n"); touch(); } });
  t.value = (obj[key] || []).join("\n");
  return t;
}
function area(obj, key) {
  const t = el("textarea", { oninput: (e) => { obj[key] = e.target.value; touch(); } });
  t.value = obj[key] || "";
  return t;
}
function numList(obj, key) {
  return el("input", { type: "text", value: (obj[key] || []).join(", "), inputmode: "decimal",
    oninput: (e) => { obj[key] = e.target.value.split(/[,\s]+/).filter(Boolean).map(Number).filter((x) => !isNaN(x)); touch(); } });
}
function slider(obj, key, min, max, step, label, hint) {
  const out = el("output", {}, fmt(obj[key]));
  const r = el("input", { type: "range", min, max, step, value: obj[key] ?? min,
    oninput: (e) => { obj[key] = +e.target.value; out.textContent = fmt(obj[key]); touch(); } });
  return el("label", { class: "f" }, el("span", {}, label, ": ", out), r, hint ? el("span", { class: "hint" }, hint) : null);
}

/* ---------------------------------------------------------------- track list */

async function loadInfo() {
  INFO = await api("studio");
  const ul = $("#track-list"); ul.replaceChildren();
  for (const t of INFO.tracks) {
    const b = el("button", { type: "button", "aria-current": T && T.id === t.id ? "true" : "false", onclick: () => openTrack(t.id) },
      t.title || t.id, el("small", {}, t.id + (t.editable ? "" : " · settings in .toml") + (t.video ? "" : " · no video yet")));
    ul.append(el("li", {}, b));
  }
}

function leaveOk() { return !dirty || confirm("You have unsaved changes. Leave them?"); }
window.addEventListener("beforeunload", (e) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } });

async function openTrack(id) {
  if (!leaveOk()) return;
  try {
    const d = await api("track/" + encodeURIComponent(id));
    T = { id, isNew: false, editable: d.editable, track: d.track, kind: d.kind, video: null, cb: null,
          hasVideo: !!d.video, videoProblem: d.video_problem, hasColorbar: d.colorbar, samples: d.samples,
          sounds: d.sounds || { music: { ...INFO.music_defaults.music }, mix: { ...INFO.music_defaults.mix }, sounds: [] } };
    dirty = false;
    await loadInfo();
    render();
  } catch (e) { fail(e); }
}

function newTrack() {
  if (!leaveOk()) return;
  const d = INFO.track_defaults;
  T = { id: "", isNew: true, editable: true, kind: "field", video: null, cb: null, hasVideo: false, hasColorbar: false, samples: [],
    track: { title: "", source: "", description: "", listening_guide: [], units: "", start_time: "", hours_per_frame: null,
      slow_down: d.slow_down, smooth_video: false, ignore: [], color_space: "rgb", max_color_distance: d.max_color_distance,
      unmatched_value: null, hot_threshold: null, cold_threshold: null, very_cold_threshold: null,
      caption_high: d.caption_high, caption_low: d.caption_low, caption_share: "", caption_share_name: d.caption_share_name,
      colorbar: { image: "colorbar.png", min: null, max: null }, map: d.map },
    sounds: { music: { ...INFO.music_defaults.music }, mix: { ...INFO.music_defaults.mix },
      sounds: [newSound("voices", "voices"), newSound("hits", "highs"), newSound("background", "background"), newSound("chime", "daily chime")] } };
  dirty = false;
  loadInfo();
  render();
}

function newSound(kind, name) {
  const s = JSON.parse(JSON.stringify(INFO.sound_defaults[kind]));
  s.kind = kind; s.name = name || kind;
  if ("range" in s) s.range = [null, null];
  if ("pitch_range" in s) s.pitch_range = [null, null];
  return s;
}

/* ---------------------------------------------------------------- the form */

function render() {
  const main = $("#editor");
  main.replaceChildren();
  if (!T) return;
  if (!T.editable) return renderReadOnly(main);
  main.append(basicsCard(), videoCard(), colorsCard(), captionsCard(), musicCard(), soundsCard(), resultCard());
  $("#actions")?.remove();
  document.body.append(actionsBar());
  if (T.hasVideo) loadVideo();
  if (T.hasColorbar && T.track.colorbar?.min !== null && T.track.colorbar?.max !== null) readColorbar(true);
  main.focus();
}

function renderReadOnly(main) {
  main.append(el("section", { class: "card" },
    el("h2", {}, T.track.title || T.id),
    el("p", {}, `This is a "${T.kind}" track: its settings are in `, el("code", {}, `tracks/${T.id}/track.toml`), " and ",
      el("code", {}, `sounds.toml`), ". You can still build, publish, export or delete it here."),
    el("p", { class: "muted" }, T.hasVideo ? "Video found." : (T.videoProblem || "No video yet: put the NASA MP4 in tracks/" + T.id + "/."))), resultCard());
  $("#actions")?.remove();
  document.body.append(actionsBar());
  main.focus();
}

function basicsCard() {
  const t = T.track;
  const idInput = el("input", { type: "text", id: "track-id", value: T.id, required: true, pattern: "[A-Za-z0-9][A-Za-z0-9_\\-]{0,40}", autocomplete: "off",
    readonly: !T.isNew || T.idLocked, placeholder: "e.g. SeaSurfaceTemp",
    oninput: (e) => { T.id = e.target.value.trim(); touch(); } });
  return el("section", { class: "card", "aria-labelledby": "h-basics" },
    el("h2", { id: "h-basics" }, "1. About the track"),
    el("p", { class: "muted" }, "Shown on the website and read out by screen readers."),
    el("div", { class: "grid" },
      field("Folder name", idInput, T.isNew ? "Letters, numbers, - and _ only. Fixed once you upload a file." : `tracks/${T.id}/`),
      field("Title", text(t, "title", { required: true, placeholder: "Sea Surface Temperature" })),
      field("Source", text(t, "source", { placeholder: "NASA Scientific Visualization Studio (SVS 1234)" })),
      field("Units", text(t, "units", { placeholder: "°C, m/s, mm/h ..." })),
      field("Description", area(t, "description"), "What the video shows, in plain words: the colors and what they mean.", "wide"),
      field("Listening guide", lines(t, "listening_guide"), "One line per sound: what to listen for.", "wide")));
}

/* -------- video */

function videoCard() {
  const t = T.track;
  T.offset = T.offset ?? 0;
  T.startLocal = T.startLocal ?? (t.start_time || "").slice(0, 16);
  const startIn = el("input", { type: "datetime-local", value: T.startLocal, oninput: (e) => { T.startLocal = e.target.value; updateStart(); } });
  const offSel = el("select", { onchange: (e) => { T.offset = +e.target.value; updateStart(); } },
    OFFSETS.map(([o, n]) => el("option", { value: o, selected: o === T.offset }, `UTC${o >= 0 ? "+" : "−"}${Math.abs(o)} ${n}`)));
  const lastIn = el("input", { type: "datetime-local", value: T.lastLocal || "", oninput: (e) => { T.lastLocal = e.target.value; computeHours(); } });
  const hours = number(t, "hours_per_frame", { id: "hours", min: 0 });
  return el("section", { class: "card", "aria-labelledby": "h-video" },
    el("h2", { id: "h-video" }, "2. The video"),
    el("div", { class: "row" },
      el("label", { class: "btn file-btn" }, T.hasVideo ? "Replace the video…" : "Upload the video (MP4)…",
        el("input", { type: "file", accept: "video/*,.mp4,.webm,.mov,.m4v", onchange: (e) => uploadFile("video", e.target.files[0]) })),
      el("span", { id: "video-info", class: "muted" }, T.hasVideo ? "Loading…" : (T.videoProblem || "No video yet."))),
    el("div", { id: "frame-area" }),
    el("h3", {}, "Time"),
    el("div", { class: "grid" },
      field("First frame shows", startIn, "The date and time printed on the first frame."),
      field("That time is in", offSel, el("span", { id: "utc-out" }, utcText())),
      field("Last frame shows (optional)", lastIn, "Fill this in and the hours per frame are worked out for you."),
      field("Hours per frame", hours, "How much time passes from one frame to the next."),
      slider(t, "slow_down", 1, 4, 0.25, "Slow down", "1 = the video's own speed. 1.5 gives the sounds more room."),
      el("div", {}, check(t, "smooth_video", "Blend frames when slowed (smoother video)"))));
}

function utcText() { return T.track.start_time ? `= ${T.track.start_time.replace("T", " ")} UTC` : ""; }
function updateStart() {
  touch();
  if (!T.startLocal) { T.track.start_time = ""; }
  else {
    const ms = Date.parse(T.startLocal + ":00Z") - T.offset * 3600e3;
    T.track.start_time = new Date(ms).toISOString().slice(0, 16);
  }
  const u = $("#utc-out"); if (u) u.textContent = utcText();
  computeHours();
}
function computeHours() {
  if (!T.lastLocal || !T.startLocal || !T.video) return;
  const h = (Date.parse(T.lastLocal + ":00Z") - Date.parse(T.startLocal + ":00Z")) / 3600e3 / (T.video.frames - 1);
  if (h > 0) { T.track.hours_per_frame = +h.toFixed(4); $("#hours").value = fmt(T.track.hours_per_frame); touch(); }
}

async function loadVideo() {
  try {
    T.video = await api("video/" + encodeURIComponent(T.id));
    const v = T.video;
    $("#video-info").textContent = `${v.name}: ${v.width}×${v.height}, ${v.frames} frames, ${v.seconds.toFixed(1)} s`;
    if (inBrowser()) $("#video-info").append(fpsControl(v));
    renderFrame();
  } catch (e) { $("#video-info").textContent = e.message; }
}

/* In the browser the frame rate is measured by playing the video for a moment; it can be corrected here. */
function fpsControl(v) {
  const input = el("input", { type: "number", min: 1, max: 120, step: "any", value: fmt(v.fps), style: "width:90px",
    "aria-describedby": "fps-hint", onchange: async (e) => {
      const fps = num(e.target.value);
      if (!fps || fps <= 0) return;
      try { await LocalStudio.setFps(T.id, fps); status("Frames per second updated.", "good"); await loadVideo(); computeHours(); }
      catch (err) { fail(err); }
    } });
  return el("span", { class: "row", style: "margin-top:6px" },
    el("label", { class: "check" }, "Frames per second:", input),
    el("span", { id: "fps-hint", class: "small" },
      v.fps_detected && Math.abs(v.fps_detected - v.fps) < 1e-6 ? "(measured from the video: change it if it's wrong)" : "(set by you)"));
}

function renderFrame() {
  const area = $("#frame-area"); if (!area || !T.video) return;
  T.frameIndex = T.frameIndex ?? 0;
  T.mode = T.mode || "boxes";
  const img = el("img", { alt: "A frame of the video", id: "frame-img" });
  const canvas = el("canvas", { width: T.video.width, height: T.video.height, "aria-hidden": "true" });
  const readout = el("p", { class: "readout", id: "readout", "aria-live": "polite" });
  const modes = el("div", { class: "row", role: "radiogroup", "aria-label": "What the mouse does on the frame" },
    ...[["boxes", "Draw boxes to ignore (logos, dates, the color bar)"], ["probe", "Check what a color reads as"]].map(([m, l]) => {
      const r = el("input", { type: "radio", name: "mode", value: m, onchange: () => { T.mode = m; readout.textContent = modeHint(); } });
      r.checked = T.mode === m;
      return el("label", { class: "check" }, r, l);
    }));
  const frameSlider = el("input", { type: "range", min: 0, max: T.video.frames - 1, value: T.frameIndex, "aria-label": "Frame",
    onchange: (e) => { T.frameIndex = +e.target.value; setFrame(img); } });
  const showMap = el("button", { type: "button", class: "btn ghost small", id: "map-toggle", onclick: () => { T.showMap = !T.showMap; setFrame(img); } });
  area.replaceChildren(
    modes,
    el("div", { class: "frame-wrap" }, img, canvas),
    el("div", { class: "row" }, el("label", { class: "f", style: "flex:1" }, "Frame", frameSlider), showMap),
    readout,
    el("h3", {}, "Boxes to ignore"),
    el("p", { class: "muted small" }, "Drag on the frame to add one, or type the numbers (video pixels: left, top, right, bottom)."),
    boxList(),
    el("button", { type: "button", class: "btn ghost small", onclick: () => { T.track.ignore.push([0, 0, 100, 100]); touch(); refreshBoxes(); } }, "+ Add a box by numbers"));
  readout.textContent = modeHint();
  setFrame(img);
  setupCanvas(canvas, readout);
}
function modeHint() { return T.mode === "probe" ? "Move the mouse over the frame to see the value it reads." : "Drag a rectangle over anything that isn't data."; }
async function setFrame(img) {
  const framePath = `frame/${encodeURIComponent(T.id)}.png?i=${T.frameIndex}&t=${Date.now()}`;
  if (T.showMap && inBrowser()) await api(framePath).catch(() => {});   // Python needs this frame for the map
  if (T.showMap) await showValueMap(img);
  if (!T.showMap) await setImg(img, framePath);
  const b = $("#map-toggle");
  if (b) b.textContent = T.showMap ? "Show the video frame" : "Show what it reads (value map)";
}

function boxList() {
  const ul = el("ul", { class: "boxes", id: "boxes" });
  T.track.ignore.forEach((b, i) => {
    const inputs = b.map((v, j) => el("input", { type: "number", value: v, style: "width:80px", "aria-label": ["left", "top", "right", "bottom"][j] + ` of box ${i + 1}`,
      oninput: (e) => { b[j] = Math.round(+e.target.value || 0); touch(); drawBoxes(); } }));
    ul.append(el("li", {}, el("span", { class: "row" }, `Box ${i + 1}:`, ...inputs,
      el("button", { type: "button", class: "btn ghost small", onclick: () => { T.track.ignore.splice(i, 1); touch(); refreshBoxes(); } }, "Remove"))));
  });
  if (!T.track.ignore.length) ul.append(el("li", { class: "muted" }, "None yet."));
  return ul;
}
function refreshBoxes() { $("#boxes")?.replaceWith(boxList()); drawBoxes(); }

let drawBoxes = () => {};
function setupCanvas(canvas, readout) {
  const ctx = canvas.getContext("2d");
  let start = null, cur = null;
  const pos = (e) => { const r = canvas.getBoundingClientRect();
    return [Math.round((e.clientX - r.left) / r.width * canvas.width), Math.round((e.clientY - r.top) / r.height * canvas.height)]; };
  drawBoxes = () => {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const lw = Math.max(2, canvas.width / 500);
    for (const [x0, y0, x1, y1] of T.track.ignore) {
      ctx.fillStyle = "rgba(0,0,0,.55)"; ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
      ctx.strokeStyle = "#F2B872"; ctx.lineWidth = lw; ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
    }
    if (start && cur) { ctx.setLineDash([10, 6]); ctx.strokeStyle = "#fff"; ctx.lineWidth = lw;
      ctx.strokeRect(start[0], start[1], cur[0] - start[0], cur[1] - start[1]); ctx.setLineDash([]); }
  };
  canvas.addEventListener("pointerdown", (e) => { if (T.mode !== "boxes") return; start = pos(e); cur = start; canvas.setPointerCapture(e.pointerId); });
  canvas.addEventListener("pointermove", (e) => {
    if (T.mode === "boxes") { if (start) { cur = pos(e); drawBoxes(); } return; }
    queueProbe(pos(e), readout);
  });
  canvas.addEventListener("pointerup", (e) => {
    if (!start) return;
    const [a, b] = start, [c, d] = pos(e); start = cur = null;
    if (Math.abs(c - a) > 4 && Math.abs(d - b) > 4) {
      T.track.ignore.push([Math.min(a, c), Math.min(b, d), Math.max(a, c), Math.max(b, d)].map((v) => Math.max(0, v)));
      touch(); refreshBoxes();
    } else drawBoxes();
  });
  drawBoxes();
}

function colorSettings() {
  const t = T.track;
  return { colorbar: t.colorbar, color_space: t.color_space, max_color_distance: t.max_color_distance, unmatched_value: t.unmatched_value, ignore: t.ignore };
}

let probeBusy = false, probeNext = null;
async function queueProbe(pt, readout) {
  probeNext = pt;
  if (probeBusy) return;                       // one at a time: the latest position goes next
  probeBusy = true;
  const slow = setTimeout(() => { readout.textContent = "Reading the colors… (the first time takes a few seconds)"; }, 400);
  while (probeNext) { const p = probeNext; probeNext = null; await probeAt(p, readout); }
  clearTimeout(slow);
  probeBusy = false;
}

async function probeAt([x, y], readout) {
  try {
    const p = await post("probe/" + encodeURIComponent(T.id), { settings: colorSettings(), x, y, frame: T.frameIndex });
    const sw = el("span", { class: "swatch", style: `background:rgb(${p.rgb})` });
    const u = T.track.units ? " " + T.track.units : "";
    let msg;
    if (p.ignored) msg = "inside a box to ignore: not used";
    else if (p.matched) msg = `reads as ${fmt(p.value.toFixed(2))}${u}`;
    else if (p.used) msg = `not on the color bar → counted as ${fmt(p.value)}${u} (the "not on the bar" value)`;
    else msg = "not on the color bar → not used";
    readout.replaceChildren(`(${x}, ${y}) `, sw, ` rgb(${p.rgb.join(", ")}): ${msg}`);
  } catch (e) { readout.textContent = e.message; }
}

/* value map: fetched as a blob because it needs the current settings */
async function showValueMap(img) {
  const b = $("#map-toggle"); if (b) b.textContent = "Working…";
  try {
    const blob = await api("valuemap/" + encodeURIComponent(T.id), { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ settings: colorSettings(), frame: T.frameIndex }) });
    img.src = URL.createObjectURL(blob);
    img.alt = "The value map: what each pixel reads as (dark = not used)";
  } catch (e) { fail(e); T.showMap = false; img.alt = "A frame of the video"; }
}

/* -------- colors */

function colorsCard() {
  const t = T.track, cb = t.colorbar;
  return el("section", { class: "card", "aria-labelledby": "h-colors" },
    el("h2", { id: "h-colors" }, "3. What the colors mean"),
    el("p", { class: "muted" }, "Upload the color bar (crop it from the NASA page or the video), then say what its two ends mean."),
    el("div", { class: "row" },
      el("label", { class: "btn file-btn" }, T.hasColorbar ? "Replace the color bar…" : "Upload the color bar (PNG/JPG)…",
        el("input", { type: "file", accept: "image/*", onchange: (e) => uploadFile("colorbar", e.target.files[0]) })),
      el("button", { type: "button", class: "btn ghost", onclick: () => readColorbar() }, "Read the color bar")),
    T.hasColorbar ? (() => { const img = el("img", { class: "cb-preview", alt: "The uploaded color bar" });
      setImg(img, `colorbar-image/${encodeURIComponent(T.id)}.png?t=${Date.now()}`); return img; })() : null,
    el("div", { id: "cb-gradient" }),
    el("div", { class: "grid" },
      field("Value at the left/bottom end", number(cb, "min", {}, cbChanged), "The number printed at that end."),
      field("Value at the right/top end", number(cb, "max", {}, cbChanged)),
      field("Ignore the bar above", number(cb, "ignore_above", {}, cbChanged), "Optional: leave out the top of the bar (e.g. when it's the same grey as land)."),
      field("Ignore the bar below", number(cb, "ignore_below", {}, cbChanged), "Optional."),
      field("Compare colors by", select(t, "color_space", [["rgb", "RGB (simple)"], ["lab", "How they look (Lab): for dark or similar colors"]], cbChanged)),
      field("How close a color must be", number(t, "max_color_distance", { min: 0 }, cbChanged), "RGB: about 40. Lab: about 12. Bigger = more pixels count."),
      field("Value for colors not on the bar", number(t, "unmatched_value"), "Empty = not used. E.g. when calm air is see-through and the bare map shows.")));
}
function cbChanged() { clearTimeout(cbChanged.t); cbChanged.t = setTimeout(() => readColorbar(true), 500); }

async function readColorbar(quiet) {
  const box = $("#cb-gradient"); if (!box) return;
  const cb = T.track.colorbar;
  if (cb.min === null || cb.max === null || cb.min === undefined || cb.max === undefined) { if (!quiet) status("Fill in the min and max values first.", "bad"); return; }
  try {
    T.cb = await post("colorbar/" + encodeURIComponent(T.id), colorSettings());
    box.replaceChildren(gradientBar(), scaleRow(T.cb.min, T.cb.max),
      el("p", { class: "muted small" }, `Found the bar at x ${T.cb.box[0]}–${T.cb.box[2]}, y ${T.cb.box[1]}–${T.cb.box[3]} of the image. ` +
        "If the colors above don't match the image, crop the image closer to the bar."));
    refreshRanges();
    if (!quiet) status("Color bar read.", "good");
  } catch (e) { if (!quiet) fail(e); else box.replaceChildren(el("p", { class: "error-text" }, e.message)); }
}
function gradientCss() {
  if (!T.cb) return "linear-gradient(90deg, #333, #999)";
  const span = (T.cb.max - T.cb.min) || 1;
  return `linear-gradient(90deg, ${T.cb.stops.map((s) => `${s.color} ${((s.value - T.cb.min) / span * 100).toFixed(1)}%`).join(", ")})`;
}
function gradientBar(band) {
  const g = el("div", { class: "gradient", style: `background:${gradientCss()}`, "aria-hidden": "true" });
  if (band) g.append(band);
  return g;
}
function scaleRow(lo, hi) {
  const u = T.track.units || "";
  return el("div", { class: "scale", "aria-hidden": "true" }, el("span", {}, fmt(lo) + " " + u), el("span", {}, fmt((lo + hi) / 2) + " " + u), el("span", {}, fmt(hi) + " " + u));
}
function barLimits() {
  if (T.cb) return [T.cb.min, T.cb.max];
  const cb = T.track.colorbar; return [num(cb.min) ?? 0, num(cb.max) ?? 100];
}

/* -------- thresholds & captions */

function captionsCard() {
  const t = T.track;
  return el("section", { class: "card", "aria-labelledby": "h-captions" },
    el("h2", { id: "h-captions" }, "4. Daily captions"),
    el("p", { class: "muted" }, "Every day of the video gets a short spoken caption (also shown on the website). These words fill it in."),
    el("div", { class: "grid" },
      field("High value", number(t, "hot_threshold"), "Above this is 'high' (e.g. 30 °C, 20 m/s)."),
      field("Low value", number(t, "cold_threshold"), "Below this counts toward the share below (e.g. 0 °C, 5 m/s)."),
      field("Very low value", number(t, "very_cold_threshold"), "Even lower (e.g. −20 °C)."),
      field("Word for the highest place", text(t, "caption_high"), "“Hottest: 41 °C over the Sahara”"),
      field("Word for the lowest place", text(t, "caption_low"), "“Coldest outside Antarctica: ...”"),
      field("The low share is…", text(t, "caption_share"), "“…% of the Northern Hemisphere is below freezing”"),
      field("Name of that share", text(t, "caption_share_name"), "“The frozen area is growing.”")));
}

/* -------- music & sounds */

function musicCard() {
  const m = T.sounds.music, x = T.sounds.mix;
  return el("section", { class: "card", "aria-labelledby": "h-music" },
    el("h2", { id: "h-music" }, "5. Key and mix"),
    el("div", { class: "grid" },
      field("Key", select(m, "key", INFO.keys)),
      field("Scale", select(m, "scale", INFO.scales)),
      slider(x, "reverb_seconds", 0, 6, 0.1, "Reverb length (s)"),
      slider(x, "reverb_wet", 0, 1, 0.05, "Reverb amount"),
      slider(x, "peak", 0.3, 0.99, 0.01, "Final loudness")));
}

function soundsCard() {
  return el("section", { class: "card", "aria-labelledby": "h-sounds" },
    el("h2", { id: "h-sounds" }, "6. Sounds"),
    el("p", { class: "muted" }, "Add as many as you like. Each one follows a range of values on the color bar."),
    el("div", { class: "row" }, Object.keys(SOUND_KINDS).map((k) =>
      el("button", { type: "button", class: "btn ghost small", title: SOUND_KINDS[k], onclick: () => {
        T.sounds.sounds.push(newSound(k, uniqueName(k))); touch(); refreshSounds(); $("#sounds .sound:last-child input")?.focus(); } }, "+ " + k))),
    el("div", { id: "sounds" }, soundCards()));
}
function uniqueName(base) { let n = base, i = 2; while (T.sounds.sounds.some((s) => s.name === n)) n = `${base} ${i++}`; return n; }
function refreshSounds() { $("#sounds").replaceChildren(...soundCards()); }
function refreshRanges() { if ($("#sounds")) refreshSounds(); }

function soundCards() {
  T.solo = T.solo || new Set();
  return T.sounds.sounds.map((s, i) => soundCard(s, i));
}

function soundCard(s, i) {
  const list = T.sounds.sounds, defs = INFO.sound_defaults[s.kind] || {};
  const card = el("article", { class: "sound" + (s.enabled === false ? " off" : ""), "aria-label": `Sound ${i + 1}: ${s.name}` });
  const move = (d) => { const j = i + d; if (j < 0 || j >= list.length) return; [list[i], list[j]] = [list[j], list[i]]; touch(); refreshSounds(); };
  const solo = el("input", { type: "checkbox", onchange: (e) => { e.target.checked ? T.solo.add(s.name) : T.solo.delete(s.name); } });
  solo.checked = T.solo.has(s.name);
  card.append(el("div", { class: "sound-head" },
    el("div", { class: "row" }, el("span", { class: "tag" }, s.kind), el("h3", {}, s.name || "(no name)")),
    el("div", { class: "row" },
      el("label", { class: "check small", title: "Preview only the ticked sounds" }, solo, "In preview"),
      el("button", { type: "button", class: "btn ghost small", onclick: () => move(-1), "aria-label": `Move ${s.name} up` }, "↑"),
      el("button", { type: "button", class: "btn ghost small", onclick: () => move(1), "aria-label": `Move ${s.name} down` }, "↓"),
      el("button", { type: "button", class: "btn danger small", onclick: () => { list.splice(i, 1); T.solo.delete(s.name); touch(); refreshSounds(); } }, "Remove"))));
  card.append(el("p", { class: "muted small" }, SOUND_KINDS[s.kind]));

  const main = el("div", { class: "grid" });
  const more = el("div", { class: "grid" });
  const keys = [...MAIN_KEYS.filter((k) => k in defs), ...Object.keys(defs).filter((k) => !MAIN_KEYS.includes(k))];
  for (const key of keys) {
    if (key === "range" || key === "pitch_range") continue;
    if (s[key] === undefined) s[key] = JSON.parse(JSON.stringify(defs[key]));
    const target = MAIN_KEYS.includes(key) ? main : more;
    target.append(soundField(s, key, defs[key], card));
  }
  card.append(main);
  if ("range" in defs) card.append(rangeBox(s, "range", s.kind === "voices" ? "Notes follow these values" :
    s.kind === "background" ? (s.measure === "mean" ? "Louder as the average goes from" : "Counts the area with values from") : "Plays where the value is from"));
  if ("pitch_range" in defs) card.append(rangeBox(s, "pitch_range", "Pitch: lowest note at … highest at (empty = same as above)"));
  card.append(el("details", { class: "more" }, el("summary", {}, "More settings"), more));
  return card;
}

function soundField(s, key, def, card) {
  const help = (INFO.sound_help || {})[key];
  const label = key.replace(/_/g, " ");
  if (key === "name") return field("Name", text(s, key, { onchange2: () => { card.querySelector("h3").textContent = s.name; } }));
  if (key === "enabled") return el("div", {}, check(s, key, ["On", el("span", { class: "skip" }, ` (${s.name})`)], () => card.classList.toggle("off", !s.enabled)));
  if (key === "volume") return slider(s, key, 0, 1, 0.01, "Volume");
  if (key === "instrument") return field("Instrument", select(s, key, s.kind === "voices" ? ["pad"] : INFO.instruments), "Used when no sample is chosen.");
  if (key === "texture") return field("Texture", select(s, key, INFO.textures), "Used when no sample is chosen.");
  if (key === "sample") return sampleField(s, card);
  if (SELECTS[key]) return field(label, select(s, key, SELECTS[key], () => { if (key === "measure") refreshSounds(); }));
  if (typeof def === "boolean") return el("div", {}, check(s, key, label));
  if (typeof def === "number") return field(label, number(s, key), help);
  if (Array.isArray(def)) return field(label, numList(s, key), help || "Numbers separated by commas.");
  return field(label, text(s, key), help);
}

function sampleField(s, card) {
  const opts = [["", "(built-in instrument)"], ...(T.samples || []).map((p) => [p, p + " (this track)"]), ...INFO.shared_samples.map((p) => [p, p + " (shared)"])];
  if (s.sample && !opts.some(([v]) => v === s.sample)) opts.push([s.sample, s.sample]);
  const up = el("input", { type: "file", accept: ".wav,audio/wav", onchange: async (e) => {
    const r = await uploadFile("sample", e.target.files[0]);
    if (r) { s.sample = r.file; if (r.note) s.root = r.note; T.samples = [...new Set([...(T.samples || []), r.file])]; touch(); refreshSounds();
      status(`Sample added${r.note ? `; it sounds like ${r.note}, so "root" is set to that` : ""}.`, "good"); }
  } });
  return el("div", {}, field("Sample (your own WAV)", select(s, "sample", opts)),
    el("label", { class: "btn ghost small file-btn", style: "margin-top:6px" }, "Upload a WAV…", up));
}

function rangeBox(s, key, title) {
  const [lo, hi] = barLimits();
  const r = s[key] = (s[key] && s[key].length ? [...s[key], null].slice(0, 2) : [null, null]);
  const band = el("div", { class: "band" });
  const place = () => {
    const a = r[0] ?? lo, b = r[1] ?? hi, span = (hi - lo) || 1;
    const L = Math.max(0, Math.min(100, (a - lo) / span * 100)), R = Math.max(0, Math.min(100, (b - lo) / span * 100));
    band.style.left = L + "%"; band.style.width = Math.max(0.5, R - L) + "%";
    band.style.display = r[0] === null && r[1] === null && key === "pitch_range" ? "none" : "";
  };
  const what = key === "range" ? "values" : "pitch";
  const end = (j, name) => {
    const step = ((hi - lo) / 200) || 0.1;
    const numIn = el("input", { type: "number", step: "any", value: fmt(r[j]), "aria-label": `${s.name} ${what}: ${name}` });
    const rng = el("input", { type: "range", min: lo, max: hi, step, value: r[j] ?? (j ? hi : lo), "aria-label": `${s.name} ${what}: ${name} (slider)`, disabled: r[j] === null });
    const none = el("input", { type: "checkbox" }); none.checked = r[j] === null;
    const set = (v) => { r[j] = v; touch(); place(); };
    numIn.addEventListener("input", () => { const v = num(numIn.value); if (v !== null) { rng.value = v; none.checked = false; rng.disabled = false; } set(v); none.checked = v === null; });
    rng.addEventListener("input", () => { numIn.value = fmt(+rng.value); set(+rng.value); });
    none.addEventListener("change", () => { rng.disabled = none.checked; if (none.checked) { numIn.value = ""; set(null); } else { const v = +rng.value; numIn.value = fmt(v); set(v); } });
    return el("div", { class: "range-row" }, el("span", {}, name), rng, numIn, el("label", { class: "check small" }, none, "no limit", el("span", { class: "skip" }, ` (${s.name} ${what}: ${name})`)));
  };
  place();
  return el("div", { class: "range-box", role: "group", "aria-label": `${s.name}: ${title}` },
    el("strong", { class: "small" }, title), gradientBar(band), scaleRow(lo, hi), end(0, "From"), end(1, "To"));
}

/* ---------------------------------------------------------------- uploads, save, build */

async function uploadFile(what, file) {
  if (!file) return null;
  if (!ID_RE.test(T.id)) { status("Fill in the folder name first (letters, numbers, - and _).", "bad"); $("#editor input")?.focus(); return null; }
  status(`Uploading ${file.name}…`);
  try {
    const r = await api(`upload/${encodeURIComponent(T.id)}/${what}?name=${encodeURIComponent(file.name)}`,
      { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: file });
    T.idLocked = true;
    const idIn = $("#track-id"); if (idIn) idIn.readOnly = true;
    if (what === "video") { T.hasVideo = true; T.track.video = ""; T.videoProblem = null; status("Video uploaded.", "good"); await loadVideo(); computeHours(); }
    if (what === "colorbar") { T.hasColorbar = true; render(); status("Color bar uploaded. Now fill in its min and max.", "good"); }
    return r;
  } catch (e) { fail(e); return null; }
}

function payload() {
  const t = { ...T.track };
  t.description = (t.description || "").trim();
  t.listening_guide = (t.listening_guide || []).map((x) => x.trim()).filter(Boolean);
  return { new: T.isNew, track: t, sounds: T.sounds };
}

async function save() {
  if (!T.editable) return true;
  if (!ID_RE.test(T.id)) { status("Fill in the folder name (letters, numbers, - and _).", "bad"); return false; }
  try {
    await post("track/" + encodeURIComponent(T.id), payload());
    const wasNew = T.isNew;
    T.isNew = false; dirty = false;
    if (wasNew) $("#actions")?.replaceWith(actionsBar());   // now it can be deleted
    await loadInfo();
    status(inBrowser() ? "Saved in this browser." : "Saved to tracks/" + T.id + "/.", "good");
    return true;
  } catch (e) { fail(e); return false; }
}

async function build(mode) {
  if (T.editable && !(await save())) return;
  if (!T.hasVideo) { status(T.videoProblem || "Upload the video first (section 2).", "bad"); return; }
  const out = $("#result"); out.hidden = false;
  const stepEl = el("p", { "aria-live": "polite" }, mode === "publish" ? "Publishing…" : "Making a preview…");
  const log = el("pre", { class: "log" });
  out.replaceChildren(el("h2", { id: "h-result", tabindex: "-1" }, mode === "publish" ? "Publishing" : "Preview"), stepEl, log);
  out.scrollIntoView({ behavior: "smooth", block: "start" });
  document.querySelectorAll("#actions button").forEach((b) => (b.disabled = true));
  try {
    const only = T.editable ? [...(T.solo || [])].filter((n) => T.sounds.sounds.some((s) => s.name === n)) : [];
    const { job } = await post("build/" + encodeURIComponent(T.id), { mode, only });
    let j;
    for (;;) {
      await new Promise((r) => setTimeout(r, 1000));
      j = await api("job/" + job);
      stepEl.textContent = j.step; log.textContent = j.log.join("\n"); log.scrollTop = log.scrollHeight;
      if (j.done) break;
    }
    if (!j.ok) { stepEl.textContent = "It stopped with an error: see the last lines below."; stepEl.className = "error-text"; status("The build failed.", "bad"); return; }
    stepEl.textContent = mode !== "publish" ? "Preview ready (the jukebox wasn't changed)." :
      inBrowser() ? "Added to your jukebox. It's saved only in this browser: use Export to share it." : "Published: it's on the jukebox now.";
    if (j.log.length) log.textContent = j.log.join("\n");
    if (j.files.audio) out.append(el("audio", { controls: true, src: j.files.audio }));
    if (j.files.graph) out.append(el("img", { src: j.files.graph, alt: "Graph of the values the sounds follow, day by day" }));
    if (mode === "publish") out.append(el("p", {}, el("a", { href: "../" }, "Open the jukebox →")));
    status(mode === "publish" ? "Published." : "Preview ready.", "good");
  } catch (e) { fail(e); }
  finally { document.querySelectorAll("#actions button").forEach((b) => (b.disabled = false)); }
}

function resultCard() { return el("section", { class: "card result", id: "result", hidden: true, "aria-labelledby": "h-result" }); }

async function exportZip(withVideo) {
  if (!(await save())) return;
  const path = `export/${encodeURIComponent(T.id)}.zip${withVideo ? "?video=1" : ""}`;
  if (!inBrowser()) { location.href = API + path; return; }
  try {
    const a = el("a", { href: URL.createObjectURL(await api(path)), download: T.id + ".zip" });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 60000);
  } catch (e) { fail(e); }
}

function actionsBar() {
  return el("div", { class: "actions", id: "actions" }, el("div", { class: "row" },
    T.editable ? el("button", { type: "button", class: "btn", onclick: save }, "Save") : null,
    el("button", { type: "button", class: "btn ghost", onclick: () => build("preview"),
      title: "Builds the sound without changing the jukebox. Tick 'In preview' on sounds to hear only those." }, "Preview the sound"),
    el("button", { type: "button", class: "btn accent", onclick: () => build("publish") }, inBrowser() ? "Add to my jukebox" : "Publish to the jukebox"),
    el("span", { class: "spacer" }),
    el("button", { type: "button", class: "btn ghost small", onclick: () => exportZip(false) }, "Export (zip)"),
    inBrowser() ? null : el("button", { type: "button", class: "btn ghost small", onclick: () => exportZip(true) }, "Export with video"),
    T.isNew ? null : el("button", { type: "button", class: "btn danger small", onclick: deleteTrack }, "Delete")));
}

async function deleteTrack() {
  if (!confirm(inBrowser()
    ? `Delete "${T.track.title || T.id}" from this browser and your jukebox? Export it first if you want to keep a copy.`
    : `Delete "${T.track.title || T.id}"? Its folder is moved to tracks/_deleted/ (you can get it back from there) and it's removed from the jukebox.`)) return;
  try {
    const r = await api("track/" + encodeURIComponent(T.id), { method: "DELETE" });
    dirty = false; T = null; $("#actions")?.remove();
    $("#editor").replaceChildren(el("section", { class: "card" }, el("h2", {}, "Deleted"), el("p", {}, r.moved_to ? "Moved to " + r.moved_to + "." : "It's gone from this browser.")));
    await loadInfo(); status("Deleted.", "good");
  } catch (e) { fail(e); }
}

async function importZip(file, overwrite = false) {
  if (!file) return;
  try {
    const r = await api(`import?overwrite=${overwrite ? 1 : 0}&name=${encodeURIComponent(file.name.replace(/\.zip$/i, "").replace(/[^A-Za-z0-9_-]/g, "_"))}`,
      { method: "POST", headers: { "Content-Type": "application/zip" }, body: file });
    await loadInfo(); status(`Imported as "${r.id}".`, "good"); dirty = false; openTrack(r.id);
  } catch (e) {
    if (e.status === 409 && confirm(e.message + (inBrowser() ? " Replace it?" : " Replace it? (The old one is moved to tracks/_deleted/.)"))) return importZip(file, true);
    fail(e);
  }
}

/* ---------------------------------------------------------------- start */

/* Is `py studio.py` serving this page? If not, we're on the public website: run Python in this browser. */
async function detectMode() {
  if (!["localhost", "127.0.0.1", "[::1]"].includes(location.hostname)) return "browser";   // a public website
  try {
    const r = await fetch(API + "studio", { cache: "no-store" });
    if (r.ok && (r.headers.get("content-type") || "").includes("json")) return "server";
  } catch { /* no server */ }
  return "browser";
}

function browserTexts() {
  document.body.classList.add("browser-mode");
  $("#subtitle").textContent = "Add your own NASA video: tell it what the colors mean, choose the sounds, and listen. " +
    "Everything happens and is saved in this browser only: nothing is uploaded anywhere.";
  $("#list-heading").textContent = "Your tracks";
  $("#side-note").textContent = "Saved only in this browser. Use Export to keep a copy or send it to the Earth Jukebox team.";
  $("#welcome").replaceChildren(
    el("h2", {}, "Make your own track"),
    el("p", {}, "Pick a NASA visualization that shows a value everywhere on a flat world map (temperature, wind, sea level…). " +
      "Upload its video and its color bar, say what the colors mean, then choose sounds for ranges of values."),
    el("p", { id: "loading", class: "muted", role: "status" }, "Starting Python in your browser…"));
}

document.addEventListener("DOMContentLoaded", async () => {
  $("#new-track").addEventListener("click", newTrack);
  $("#import-file").addEventListener("change", (e) => { importZip(e.target.files[0]); e.target.value = ""; });
  MODE = await detectMode();
  if (inBrowser()) {
    browserTexts();
    const buttons = [$("#new-track"), $("#import-file")];
    buttons.forEach((b) => (b.disabled = true));
    try {
      await LocalStudio.start((text) => { $("#loading").textContent = text; });
    } catch (e) {
      $("#loading").textContent = "Python couldn't start in this browser: " + e.message + " Try a recent Chrome, Edge, Firefox or Safari.";
      $("#loading").className = "error-text";
      return;
    }
    $("#loading").textContent = "Ready. Press “New track” to start.";
    buttons.forEach((b) => (b.disabled = false));
  }
  try {
    await loadInfo();
    if (inBrowser() && !INFO.tracks.length) $("#track-list").append(el("li", { class: "muted small" }, "None yet."));
    const want = new URLSearchParams(location.search).get("track");
    if (want === "new") newTrack(); else if (want) openTrack(want);
  } catch (e) { fail(inBrowser() ? e : new Error("Can't reach the studio. Start it with:  py studio.py")); }
});
