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
    "kind": "categories",             # data drawn only where it happens (rain), with a color bar
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

GMAO_T2M = {
    "id": "gmao_t2m",
    "kind": "field",                  # a value everywhere on the map (see jukebox/field.py)
    "title": "Near-Surface Temperature (GEOS-FP)",
    "source": "NASA GMAO GEOS-FP model, NASA Scientific Visualization Studio (SVS 5147)",
    "description": (
        "A flat map of the whole Earth showing the air temperature 2 meters above the ground, "
        "hour by hour from 30 October to 14 November 2026, from NASA's GEOS-FP weather model. "
        "Colors run from dark blue, white and purple (-40 C) through blue, cyan, yellow, orange "
        "and red to dark red and grey (+40 C). The tropics stay warm and steady, deserts heat up "
        "every afternoon, and the Arctic, Siberia and northern Canada get colder as winter arrives."
    ),
    "listening_guide": [
        "Five held voices, one for each band of latitude, from the Arctic to Antarctica. Warmer = higher. Each step up or down is about 1 degree C.",
        "Listen to the Arctic voice sink as winter sets in, and the Antarctic voice rise with the southern spring.",
        "Plucks = places hotter than 30 C. Hotter = higher and louder.",
        "Every day the plucks sweep from right to left: afternoon heat moves west with the sun, from Asia to Africa to the Americas.",
        "Wind = how much of the Northern Hemisphere is below freezing. It grows as winter comes.",
        "A chime rings at the start of every day (midnight UTC).",
    ],

    "start_time": "2026-10-30T09:00",   # 30 Oct 05:00 EDT on the first frame = 09:00 UTC
    "hours_per_frame": 1.0,
    "slow_down": 1.5,
    "smooth_video": True,               # blend frames so the slowed video isn't choppy

    "map": {"lon_min": -180, "lon_max": 180, "lat_max": 90, "lat_min": -90},

    # Official color bar image (from the SVS 5147 page) and what its two ends mean.
    # The bar is found in the image automatically.
    "colorbar": {"image": "colorbars/gmao_t2m.png", "min": -40, "max": 40},
    "units": "C",
    "max_color_distance": 40,           # pixels further than this from any scale color are ignored
    "ignore": [
        (0, 0, 360, 80),                # NASA / GMAO logo
        (0, 920, 505, 1024),            # date/time stamp
    ],
    "hot_threshold": 30,                # "hot" for the heat plucks
    "cold_threshold": 0,                # freezing
    "very_cold_threshold": -20,

    "sounds": "sounds/gmao_t2m.toml",
}


WindSpeed = {
    "id": "WindSpeed",
    "kind": "field",                  # a value everywhere on the map (see jukebox/field.py)
    "title": "Near-Surface Wind Speed (GEOS-FP)",
    "source": "NASA GMAO GEOS-FP model, NASA Scientific Visualization Studio (SVS 5147)",
    "description": (
        "A flat map of the whole Earth showing how fast the wind blows 10 meters (about 30 feet) above the ground, "
        "hour by hour, from NASA's GEOS-FP weather model. Colors run from pale lavender and purple for light winds,"
        "through blue, cyan, yellow and orange, to red for strong winds (around 20 meters per second), "
        "and dark red, brown and grey for hurricane-force winds (up to 40 meters per second, about 145 km/h).  "
        "Winds are strongest over the oceans, where there is little to slow them down,"
        "and swirling bands of color show weather fronts and storms moving around the globe."
    ),
    "listening_guide": [],

    "start_time": "2026-10-30T09:00",   # 30 Oct 05:00 EDT on the first frame = 09:00 UTC
    "hours_per_frame": 1.1667
    "slow_down": 1.5,
    "smooth_video": True,               # blend frames so the slowed video isn't choppy

    "map": {"lon_min": -180, "lon_max": 180, "lat_max": 90, "lat_min": -90},

    # Official color bar image (from the SVS 5147 page) and what its two ends mean.
    # The bar is found in the image automatically.
    "colorbar": {"image": "colorbars/NearSurfaceWindSpeed_colorbar_plain.png", "min": -40, "max": 40},
    "units": "C",
    "max_color_distance": 40,           # pixels further than this from any scale color are ignored
    "ignore": [
        (0, 0, 360, 80),                # NASA / GMAO logo
        (0, 920, 505, 1024),            # date/time stamp
    ],
    "fast_threshold": 20,                # "hot" for the heat plucks
    "slow_threshold": 10,                # freezing
    "very_cold_threshold": 5,

    "sounds": "sounds/WindSpeed.toml",
}

PRESETS = {p["id"]: p for p in [IMERG, GMAO_T2M, WindSpeed]}
