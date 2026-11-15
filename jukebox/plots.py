"""Step 3: plot the features before making any sound, to check they make sense."""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .features import series


def plot_features(feats, times, layers, out_path, day_starts=()):
    fig, axes = plt.subplots(4, 1, figsize=(11, 9), sharex=True)
    colors = {"liquid": "#2a9d4a", "frozen": "#3b6fd8"}

    ax = axes[0]
    for name in layers:
        ax.plot(times, series(feats, name, "area") * 100, label=name, color=colors.get(name))
    ax.set_ylabel("% of globe\ncovered")
    ax.legend(loc="upper right", frameon=False)

    ax = axes[1]
    for name in layers:
        ax.plot(times, series(feats, name, "heavy") * 100, color=colors.get(name))
    ax.set_ylabel("% of globe\nheavy (>=10 mm/h)")

    ax = axes[2]
    band = series(feats, "liquid", "band_area").T * 100
    ax.imshow(band, aspect="auto", origin="lower", cmap="Greens",
              extent=[times[0], times[-1], -180, 180])
    ax.set_ylabel("rain by longitude\n(W -> E)")

    ax = axes[3]
    ax.plot(times, [f["change"] for f in feats], color="#888")
    ax.set_ylabel("change\n(motion)")
    ax.set_xlabel("seconds (in the slowed-down soundtrack)")

    for a in axes:
        for d in day_starts:
            a.axvline(d, color="#bbb", lw=0.6, zorder=0)
        a.spines[["top", "right"]].set_visible(False)

    fig.suptitle("Features extracted from the video (grey lines = new day)")
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)


def plot_field(feats, times, out_path, day_starts=(), units="C", hot=None, cold=None):
    from .field import LAT_NAMES
    fig, axes = plt.subplots(4, 1, figsize=(11, 9), sharex=True)

    ax = axes[0]
    ax.plot(times, [f["mean"] for f in feats], color="#c0392b")
    ax.set_ylabel(f"global mean\n({units})")

    ax = axes[1]
    lat = np.array([f["lat_mean"] for f in feats])
    for b, name in enumerate(LAT_NAMES):
        ax.plot(times, lat[:, b], label=name)
    ax.set_ylabel(f"latitude bands\n({units}) = voices")
    ax.legend(loc="center left", bbox_to_anchor=(1.0, 0.5), frameon=False, fontsize=8)

    ax = axes[2]
    hot_map = np.array([f["band_hot"] for f in feats]).T * 100
    ax.imshow(hot_map, aspect="auto", origin="lower", cmap="Reds", extent=[times[0], times[-1], -180, 180])
    ax.set_ylabel(f"area above {hot} {units}\nby longitude (W -> E)")

    ax = axes[3]
    ax.plot(times, [f["freeze_nh"] * 100 for f in feats], color="#3b6fd8")
    ax.set_ylabel(f"% of N. Hemisphere\nbelow {cold} {units}")
    ax.set_xlabel("seconds (in the soundtrack)")

    for a in axes:
        for d in day_starts:
            a.axvline(d, color="#bbb", lw=0.6, zorder=0)
        a.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Features extracted from the video (grey lines = new day)")
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
