"""Rough place names for a latitude/longitude, used in the spoken descriptions.

These are deliberately simple boxes: good enough to say "near Southeast Asia"
or "over the South Pacific", not a real geography library.
"""

# (name, lat_min, lat_max, lon_min, lon_max) - first match wins
LAND = [
    ("Antarctica", -90, -60, -180, 180),
    ("Greenland", 59, 84, -73, -12),
    ("Southeast Asia", -11, 22, 92, 155),
    ("Australia", -45, -10, 112, 155),
    ("Europe", 35, 72, -25, 45),
    ("Africa", -35, 37, -20, 52),
    ("Asia", 0, 80, 45, 180),
    ("North America", 7, 84, -170, -50),
    ("South America", -56, 13, -82, -34),
]


def ocean_name(lat, lon):
    if lat > 66:
        return "the Arctic Ocean"
    if lat < -50:
        return "the Southern Ocean"
    if 30 <= lat <= 46 and -6 <= lon <= 36:
        return "the Mediterranean"
    if 20 <= lon <= 120 and lat < 25:
        basin = "Indian Ocean"
    elif -70 <= lon < 20 or (lat > 8 and -100 <= lon < 20):
        basin = "Atlantic"
    else:
        basin = "Pacific"
    if basin == "Indian Ocean":
        return "the Indian Ocean"
    if abs(lat) < 15:
        return f"the tropical {basin}"
    return f"the {'North' if lat > 0 else 'South'} {basin}"


def place_name(lat, lon, is_land):
    if is_land:
        for name, la0, la1, lo0, lo1 in LAND:
            if la0 <= lat <= la1 and lo0 <= lon <= lo1:
                return name
    return ocean_name(lat, lon)
