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
