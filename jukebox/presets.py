"""Presets: everything that is specific to one visualization lives here.

The engine (video.py, palette.py, features.py, compose.py) is generic.
To add a new visualization, copy the IMERG preset and change:
  - where its color bar(s) are and what values they mean
  - which screen areas to ignore (legend, timestamp, logos)
  - how many hours of data each frame represents
  - "sounds": which sound settings file to use (sounds/*.toml)

All pixel coordinates are for the ORIGINAL video resolution (here 1920x1080).
"""

IMERG = {
    "id": "imerg",
    "title": "Global Rain and Snow (IMERG)",
    "source": "NASA GPM IMERG precipitation, NASA Scientific Visualization Studio",
    # Text for the website (shown and read by screen readers)
    "description": (
        "A flat map of the whole Earth, showing a week of rain and snow measured by "
        "NASA's Global Precipitation Measurement satellites (IMERG), in half-hour steps. "
        "Rain is drawn in green, yellow and red (light to heavy); snow in light blue to purple. "
        "Rain bands sweep across the oceans from west to east, a belt of storms circles "
        "the tropics, and snow falls mostly near the poles."
    ),
    "listening_guide": [
        "Raindrops: each pluck is rain somewhere on Earth. More drops = more rain.",
        "Left to right in your headphones = west to east on the map.",
        "Higher drops = rain further north, lower drops = further south.",
        "Low rumble and booms = heavy downpours (10 mm per hour or more).",
        "High glassy bells = snow.",
        "The warm chord swells as rain spreads and fades as it shrinks; it changes and a chime rings at the start of every day.",
    ],

    # --- Time --------------------------------------------------------------
    "start_time": "2026-11-07T00:00",   # timestamp shown on the first frame
    "hours_per_frame": 0.5,             # each frame = 30 minutes of data
    "slow_down": 2.0,                   # play 2x slower so the ear can follow

    # --- Map projection -----------------------------------------------------
    # Equirectangular world map filling the whole frame:
    # x: 180°W (left) -> 180°E (right), y: 90°N (top) -> 90°S (bottom)
    "map": {"lon_min": -180, "lon_max": 180, "lat_max": 90, "lat_min": -90},

    # --- Color bars ---------------------------------------------------------
    # Each layer has a color bar made of equal-width bins. We sample the color
    # in the middle of every bin straight from the video and give it a value.
    # Bin values = geometric middle of the labelled edges (0.1-0.2 -> 0.14 ...).
    "layers": {
        "liquid": {
            "label": "rain",
            "bar_x0": 920, "bin_width": 36, "bar_y": 1017,
            "edges": [0.1, 0.2, 0.3, 0.5, 1.0, 2.0, 3.0, 5.0, 10, 20, 50],
            "units": "mm/hour",
        },
        "frozen": {
            "label": "snow",
            "bar_x0": 1360, "bin_width": 36, "bar_y": 1017,
            "edges": [0.1, 0.2, 0.3, 0.5, 1.0, 2.0, 3.0, 5.0, 10, 20, 50],
            "units": "mm/hour",
        },
    },
    # How strict the color matching is (see palette.build_lut)
    "color_match": {"min_sat": 0.45, "min_val": 0.35, "max_hue_dist": 25},
    # A pixel only counts as data if it differs this much from the bare map
    "min_background_diff": 45,

    # Rectangles to ignore: (x0, y0, x1, y1) in original pixels
    "ignore": [
        (880, 975, 1760, 1080),   # both legends
        (30, 905, 400, 970),      # date/time stamp
        (1850, 990, 1920, 1060),  # logo in the bottom-right corner
    ],

    # Rain rate that counts as "heavy" (red part of the color bar)
    "heavy_threshold": 10.0,

    # --- Sound ------------------------------------------------------------
    # All instruments, volumes, notes and mappings: edit this file
    "sounds": "sounds/imerg.toml",
}

PRESETS = {p["id"]: p for p in [IMERG]}
