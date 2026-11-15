// Shows an "Add or edit tracks" link in the Tracks panel, but only when the site is served by
// `py studio.py` (your own computer). On the public website /api/studio doesn't exist, so nothing appears.
(async () => {
  try {
    const r = await fetch("api/studio", { cache: "no-store" });
    if (!r.ok || !(r.headers.get("content-type") || "").includes("json")) return;
  } catch { return; }
  const list = document.getElementById("track-list");
  if (!list) return;
  const a = document.createElement("a");
  a.href = "studio/";
  a.className = "studio-link";
  a.textContent = "+ Add or edit tracks (studio)";
  a.style.cssText = "display:inline-block;margin-top:12px;color:#F2B872;font-weight:600;font-size:14px;";
  list.after(a);
})();
