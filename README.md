# Earth Jukebox

Turning NASA Earth Information Center visualizations into music, so the data can be
heard as well as seen. Built for the "Earth Jukebox" challenge.

**Tracks:**
- **Global Rain and Snow (IMERG):** a week of rain and snow, 7–14 Nov 2026 (`imerg`)
- **Near-Surface Temperature (GEOS-FP):** hourly air temperature, 30 Oct–14 Nov 2026 (`gmao_t2m`)

## How it works

```
video ──► read frames ──► colors → numbers ──► features ──► music ──► WAV
           (OpenCV)       (the map's own        (how much,    (numpy      │
                           color bar)            where, how    synth)      ▼
                                                 heavy)               website video
                                                     │                 + captions
                                                     └──► daily descriptions (WebVTT)
```

1. **Colors → numbers.** We read the legend colors straight from the video, then match
   every pixel to the nearest legend color *by hue* (hue survives the semi-transparent
   drawing and video compression). A pixel only counts if it also differs from the bare
   background map, so deserts and forests are never mistaken for rain.
2. **Features.** Per frame: share of the globe with rain/snow (weighted by real area,
   because a flat map stretches the poles), heavy rain, rain per 30° longitude band, its
   average latitude, and where the most rain is.
3. **Music.** Features are mapped to sound:

| What you see                              | What you hear                                   |
|-------------------------------------------|-------------------------------------------------|
| Rain anywhere on Earth                    | Raindrops (marimba plucks)                      |
| …total amount of rain                     | …how many drops per second                      |
| …west → east on the map                   | …left → right in your headphones                |
| …further north                            | …higher pitch                                   |
| …more intense                             | …louder drop                                    |
| Heavy rain (≥ 10 mm/hour)                 | Low thunder rumble, booms at peaks              |
| Snow                                      | High glassy bells                               |
| Global rain coverage (daily pulse)        | Warm chord that swells and fades                |
| A new day (00:00 UTC)                     | Chime + chord change (one chord per day)        |

Notes always come from one scale (D major pentatonic by default), so it stays musical
however the data moves. The video is slowed down 2× so the ear can follow (one day ≈ 3.2
seconds).

4. **Accessibility.** One sentence per day ("Fri 13 Nov. Most rain near the North
   Atlantic… Heavy rain is building: more thunder.") is written as captions and read out
   by screen readers while playing. The site works fully with keyboard and screen reader.

## Setup (once)

```
py -m pip install -r requirements.txt
winget install ffmpeg
```

(On Mac/Linux: `python3 -m pip ...` and install ffmpeg with your package manager.)

## Make a track

Put the source video in `videos/`, then:

```
py sonify.py imerg videos/imergert_1080p_30.mp4
py sonify.py gmao_t2m videos/gmao_t2m_2048x1024.mp4
```

The first run takes about half a minute; after that the video analysis is cached, so
re-running with different sounds takes a few seconds. Results:

(Examples use `imerg`; every track works the same way.)

- `output/imerg/sonification.wav`: the soundtrack
- `output/imerg/features.png`: plot of the numbers (look at this first when tuning)
- `output/imerg/features.csv`: the numbers per frame
- `output/imerg/descriptions.vtt`: the daily descriptions
- `website/media/imerg.mp4`: video + soundtrack for the website
- `website/tracks.json`: track list, updated automatically

## Change the sounds

Everything about a track's sound is in its own file, **`sounds/imerg.toml`** or
**`sounds/gmao_t2m.toml`**, a commented settings file:
key, scale, chords, each layer's instrument, volume, and how the data drives it (drops per
second, note range, loudness, thunder threshold, …). Edit it and re-run:

```
py sonify.py imerg videos/imergert_1080p_30.mp4 --no-video
```

**Use your own instruments:** put a WAV file in `samples/` and set, for example:

```toml
[drops]
sample = "samples/my_piano_C4.wav"
root = "C4"
```

See `samples/README.md` for which kinds of samples work for which layer. To hear an
example, try `--sounds sounds/imerg_samples_demo.toml`.

Built-in instruments: `marimba`, `bell`, `pluck`, `sine` (notes), `pad` (chords),
`rumble`, `noise` (thunder textures).

Handy options while tweaking:

| Option | What it does |
|---|---|
| `--no-video` | skip building the website video (faster) |
| `--only drops,thunder` | hear only those layers (rain: `pad, drops, thunder, snow, chime`; temperature: `choir, heat, frost, chime`) |
| `--stems` | also save each layer as its own WAV in `output/imerg/stems/` |
| `--sounds sounds/x.toml` | use another settings file, so you can keep several versions |
| `--seed 3` | a different random arrangement of the drops |
| `--reanalyze` | redo the video analysis (only needed if you change `presets.py`) |

When you're happy, run once **without** `--no-video` / `--only` to update the website.

## Run the website

```
cd website
py -m http.server 8000
```

Open http://localhost:8000. (Opening `index.html` directly won't work, because browsers
block loading `tracks.json` from a file.)

## The temperature track

Temperature covers the whole map, so it gets its own music (`jukebox/compose_field.py`):

| What you see                                        | What you hear                                  |
|-----------------------------------------------------|------------------------------------------------|
| Average temperature of 5 bands of latitude          | 5 held voices; 1 °C warmer = one note higher   |
| Places above 30 °C                                  | Plucks; hotter = higher and louder             |
| …where, west → east                                 | …left → right: they sweep right→left every day as afternoon heat follows the sun |
| Share of the Northern Hemisphere below freezing     | Wind that grows as winter comes                |
| A new day (midnight UTC)                            | Chime                                          |

Colors are turned into °C with NASA's own color bar image (`colorbars/gmao_t2m.png`,
from SVS page 5147). The bar is found in the image automatically, and only its two ends
(−40 and 40) are written in the preset.

## Add a new visualization

Two kinds of video work:
- **"field"**: a value everywhere on a flat world map (temperature, sea surface
  temperature, …). Copy the `GMAO_T2M` preset.
- **"categories"**: data only where something happens, with its color bar inside the
  video (rain, …). Copy the `IMERG` preset.

For a "field" video:
1. Put the video in `videos/` and its color bar image in `colorbars/` (a screenshot of
   the bar is fine).
2. In `jukebox/presets.py`, copy the `GMAO_T2M` block and change: `id`, the texts, the
   `colorbar` image and its `min`/`max`, `start_time` and `hours_per_frame` (read the
   timestamps of the first two frames), and `sounds`. Optional: `ignore` boxes for logos
   or labels drawn on top of the map. Add it to `PRESETS` at the bottom.
3. Copy `sounds/gmao_t2m.toml` to `sounds/<id>.toml` and pick your instruments/samples.
4. Run `py sonify.py <id> videos/<file>.mp4` and check `output/<id>/features.png`.

## Project structure

```
sonify.py            run the whole pipeline
sounds/              sound settings (.toml): instruments, volumes, notes, mappings
samples/             your own instrument WAV files
colorbars/           color bar images (for "field" tracks)
jukebox/
  presets.py         everything specific to one visualization (analysis side)
  config.py          reads the sound settings, with defaults
  video.py           reading frames
  palette.py         color bar → numbers (rain track: bar inside the video)
  colorbar.py        reads a color bar image (finds the bar automatically)
  features.py        numbers per frame (rain track)
  field.py           numbers per frame (temperature track)
  timeline.py        frame → date and soundtrack time
  compose.py         the mapping from features to music (the "score", rain track)
  compose_field.py   the score for the temperature track
  instruments.py     built-in synths + loading/pitching/looping your WAV samples
  synth.py           low-level helpers (panning, pad tone, rumble, reverb)
  describe.py        accessible descriptions + CSV
  plots.py           feature plots
website/             the jukebox site (static: HTML/CSS/JS)
```

Visualizations: NASA Scientific Visualization Studio / Earth Information Center.
