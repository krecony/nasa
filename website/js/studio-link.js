// The "add a track" link under the track list.
// With `py studio.py` (your own computer) it opens the studio, which saves into tracks/.
// On the public website the same page runs in the visitor's browser and saves only there.
(async () => {
  let server = false;
  const onThisComputer = ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);
  if (onThisComputer) try {
    const r = await fetch("api/studio", { cache: "no-store" });
    server = r.ok && (r.headers.get("content-type") || "").includes("json");
  } catch { /* no studio server: the public website */ }
  const list = document.getElementById("track-list");
  if (!list) return;
  const a = document.createElement("a");
  a.href = "studio/";
  a.className = "studio-link";
  a.textContent = server ? "+ Add or edit tracks (studio)" : "+ Add your own track";
  a.style.cssText = "display:inline-block;margin-top:12px;color:#F2B872;font-weight:600;font-size:14px;";
  list.after(a);
})();
