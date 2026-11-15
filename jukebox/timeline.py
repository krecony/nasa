"""When is each frame? Turns frame numbers into data dates and soundtrack seconds."""

from datetime import datetime, timedelta

import numpy as np


def find_data_end(feats, min_share=0.9):
    """Index of the first frame of the still 'hold' at the end of the video.

    Many SVS videos pause on the last frame. We find the earliest frame after
    which (almost) every frame is a repeat.
    """
    hold = np.array([f["hold"] for f in feats], dtype=float)
    n = len(hold)
    tail_share = np.cumsum(hold[::-1])[::-1] / np.arange(n, 0, -1)   # share of holds from i to end
    for i in range(n):
        if tail_share[i] >= min_share and hold[i]:
            return i
    return n


def build_timeline(feats, preset, fps):
    n = len(feats)
    data_end = find_data_end(feats)
    start = datetime.fromisoformat(preset["start_time"])
    step = timedelta(hours=preset["hours_per_frame"])
    dates = [start + step * min(i, data_end - 1) for i in range(n)]
    seconds_per_frame = preset["slow_down"] / fps

    # frames where a new day (UTC) starts: the first frame of each new date,
    # so it also works when frames don't land exactly on midnight (e.g. 70-minute steps)
    day_starts = [0] + [i for i in range(1, data_end) if dates[i].date() != dates[i - 1].date()]
    day_of_frame = np.searchsorted(day_starts, np.arange(n), side="right") - 1

    return {
        "n_frames": n,
        "data_end": data_end,
        "dates": dates,
        "seconds_per_frame": seconds_per_frame,
        "frame_time": np.arange(n) * seconds_per_frame,
        "duration": n * seconds_per_frame,
        "day_starts": day_starts,
        "day_of_frame": day_of_frame,
    }
