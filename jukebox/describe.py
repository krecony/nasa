"""Accessible descriptions: one short sentence per day, as a WebVTT file.

The website shows these as captions and announces them to screen readers,
so someone who can't see the map still knows what they're hearing.
"""

from collections import Counter

import numpy as np

from .features import series


def vtt_time(s):
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{sec:06.3f}"


def day_cues(feats, tl):
    """Returns a list of (start_s, end_s, text)."""
    cues = []
    ft, data_end = tl["frame_time"], tl["data_end"]
    starts = tl["day_starts"]
    ends = starts[1:] + [data_end]
    rain = series(feats, "liquid", "area") * 100
    snow = series(feats, "frozen", "area") * 100
    heavy = series(feats, "liquid", "heavy") * 100
    snow_lat = series(feats, "frozen", "lat_c")
    prev_heavy = None

    for d0, d1 in zip(starts, ends):
        if d1 <= d0:
            continue
        date = tl["dates"][d0]
        label = f"{date:%a %d %b}"
        if d1 == data_end and (d1 - d0) * (tl["dates"][1] - tl["dates"][0]).total_seconds() < 23 * 3600:
            label += f" (until {tl['dates'][d1 - 1]:%H:%M} UTC)"
        place = Counter(f["hot_place"] for f in feats[d0:d1]).most_common(1)[0][0]
        h = heavy[d0:d1].mean()
        trend = ""
        if prev_heavy:
            if h > prev_heavy * 1.25:
                trend = " Heavy rain is building: more thunder."
            elif h < prev_heavy * 0.8:
                trend = " Heavy rain is easing."
        prev_heavy = h
        snow_where = "far north" if snow_lat[d0:d1].mean() > 0 else "far south"
        text = (f"{label}. Most rain near {place}. "
                f"Rain covers {rain[d0:d1].mean():.1f}% of the globe; "
                f"snow {snow[d0:d1].mean():.1f}%, mostly in the {snow_where}.{trend}")
        cues.append((ft[d0], ft[d1] if d1 < len(ft) else tl["duration"], text))

    if data_end < tl["n_frames"]:
        last = tl["dates"][data_end - 1]
        cues.append((ft[data_end], tl["duration"] + 2.0,
                     f"End of the data: {last:%d %b %H:%M} UTC. The sound fades out."))
    return cues


def write_vtt(cues, path):
    lines = ["WEBVTT", ""]
    for i, (a, b, text) in enumerate(cues, 1):
        lines += [str(i), f"{vtt_time(a)} --> {vtt_time(b)}", text, ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_csv(feats, tl, layers, path):
    import csv
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        head = ["frame", "soundtrack_s", "date_utc"]
        for name in layers:
            head += [f"{name}_area_pct", f"{name}_rate_mm_h", f"{name}_heavy_pct", f"{name}_lon_c", f"{name}_lat_c"]
        head += ["most_rain_near", "change", "hold"]
        w.writerow(head)
        for i, f in enumerate(feats):
            row = [i, round(tl["frame_time"][i], 3), tl["dates"][i].strftime("%Y-%m-%d %H:%M")]
            for name in layers:
                L = f[name]
                row += [round(L["area"] * 100, 3), round(L["rate"], 4), round(L["heavy"] * 100, 4),
                        round(L["lon_c"], 1), round(L["lat_c"], 1)]
            row += [f["hot_place"], round(f["change"], 4), int(f["hold"])]
            w.writerow(row)


# --- field tracks (e.g. temperature) ------------------------------------------------

def field_cues(feats, tl, preset):
    """One sentence per day for a field track: hottest/coldest place, freezing share."""
    u = preset.get("units", "")
    deg = "°C" if u == "C" else (" " + u if u else "")
    cues = []
    ft, data_end = tl["frame_time"], tl["data_end"]
    starts = tl["day_starts"]
    ends = starts[1:] + [data_end]
    step_h = preset["hours_per_frame"]
    freeze = np.array([f["freeze_nh"] for f in feats]) * 100
    prev = None
    for d0, d1 in zip(starts, ends):
        if d1 <= d0:
            continue
        label = f"{tl['dates'][d0]:%a %d %b}"
        if tl["dates"][d0].hour != 0:
            label += f" (from {tl['dates'][d0]:%H:%M} UTC)"
        elif (d1 - d0) * step_h < 23:
            label += f" (until {tl['dates'][d1 - 1]:%H:%M} UTC)"
        day = feats[d0:d1]
        hot = max(day, key=lambda f: f["hottest"][0])
        cold = min(day, key=lambda f: f["coldest"][0])
        fz = freeze[d0:d1].mean()
        trend = ""
        if prev is not None:
            if fz > prev + 0.5:
                trend = " The frozen area is growing."
            elif fz < prev - 0.5:
                trend = " The frozen area is shrinking."
        prev = fz
        text = (f"{label}. Hottest: {hot['hottest_place']}, about {hot['hottest'][0]:.0f}{deg}. "
                f"Coldest outside Antarctica: {cold['coldest_place']}, about {cold['coldest'][0]:.0f}{deg}. "
                f"{fz:.0f}% of the Northern Hemisphere is below freezing.{trend}")
        end = ft[d1] if d1 < len(ft) else tl["duration"] + 2.0
        cues.append((ft[d0], end, text))
    return cues


def write_field_csv(feats, tl, path):
    import csv
    from .field import LAT_NAMES
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["frame", "soundtrack_s", "date_utc", "global_mean"] + [f"mean_{n}" for n in LAT_NAMES]
                   + ["hot_area_pct", "freeze_nh_pct", "freeze_area_pct", "very_cold_area_pct",
                      "hottest", "hottest_place", "coldest_outside_antarctica", "coldest_place"])
        for i, f in enumerate(feats):
            w.writerow([i, round(tl["frame_time"][i], 3), tl["dates"][i].strftime("%Y-%m-%d %H:%M"),
                        round(f["mean"], 2)] + [round(x, 2) for x in f["lat_mean"]]
                       + [round(f["hot_area"] * 100, 3), round(f["freeze_nh"] * 100, 2),
                          round(f["freeze_area"] * 100, 2), round(f["cold_area"] * 100, 2),
                          round(f["hottest"][0], 1), f["hottest_place"], round(f["coldest"][0], 1), f["coldest_place"]])
