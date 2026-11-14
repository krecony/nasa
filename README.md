# Earth Jukebox

Turning NASA Earth Information Center visualizations into music, so the data can be
heard as well as seen. Built for the "Earth Jukebox" challenge.

**First track:** a week of global rain and snow (NASA GPM IMERG), 7–14 Nov 2026.

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
```

The first run takes about half a minute; after that the video analysis is cached, so
re-running with different sounds takes a few seconds. Results:

- `output/imerg/sonification.wav`: the soundtrack
- `output/imerg/features.png`: plot of the numbers (look at this first when tuning)
- `output/imerg/features.csv`: the numbers per frame
- `output/imerg/descriptions.vtt`: the daily descriptions
- `website/media/imerg.mp4`: video + soundtrack for the website
- `website/tracks.json`: track list, updated automatically

## Change the sounds

Everything about the sound is in **`sounds/imerg.toml`**, a commented settings file:
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
| `--only drops,thunder` | hear only those layers (`pad, drops, thunder, snow, chime`) |
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

## Add a new visualization

1. Download the video into `videos/`.
2. In `jukebox/presets.py`, copy the `IMERG` preset and change: the color bar position
   and values, the areas to ignore (legend, timestamp, logo), `start_time`,
   `hours_per_frame`, the texts, and `sounds` (copy `sounds/imerg.toml` to start).
3. Add it to `PRESETS` at the bottom and run `py sonify.py <id> videos/<file>.mp4`.

For a visualization without a color bar (e.g. white clouds) you'd swap the palette
matching for a simple brightness/saturation mask in `features.py`.

## Project structure

```
sonify.py            run the whole pipeline
sounds/              sound settings (.toml): instruments, volumes, notes, mappings
samples/             your own instrument WAV files
jukebox/
  presets.py         everything specific to one visualization (analysis side)
  config.py          reads the sound settings, with defaults
  video.py           reading frames
  palette.py         color bar → numbers
  features.py        numbers per frame
  timeline.py        frame → date and soundtrack time
  compose.py         the mapping from features to music (the "score")
  instruments.py     built-in synths + loading/pitching/looping your WAV samples
  synth.py           low-level helpers (panning, pad tone, rumble, reverb)
  describe.py        accessible descriptions + CSV
  plots.py           feature plots
website/             the jukebox site (static: HTML/CSS/JS)
```

Visualizations: NASA Scientific Visualization Studio / Earth Information Center.
