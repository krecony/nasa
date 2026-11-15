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

## Tracks live in folders

Every visualization is one folder in `tracks/`; the folder name is the track's name:

```
tracks/WindSpeed/
  track.toml     what the video is: title, description, dates, what the colors mean
  sounds.toml    how it sounds: instruments, samples, volumes, mappings
  colorbar.png   the color bar image ("field" tracks)
  video.mp4      the original NASA video (not in git: put it here yourself)
  samples/       optional: WAVs only this track uses
```

## Make a track

Put the NASA video in its track folder (or in `videos/`), then:

```
py sonify.py imerg            one track
py sonify.py --all            every track
py sonify.py --list           which tracks there are, and whether their video is in place
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

Everything about a track's sound is in its own file, **`tracks/<name>/sounds.toml`**,
a commented settings file: key, scale, every sound's instrument, volume, and how the data
drives it. Edit it and re-run:

```
py sonify.py imerg --no-video
```

**Use your own instruments:** put a WAV file in `samples/` (shared by all tracks) or in
`tracks/<name>/samples/` (just that track) and set, for example:

```toml
[drops]
sample = "samples/my_piano_C4.wav"
root = "C4"
```

See `samples/README.md` for which kinds of samples work for which layer. To hear an
example, try `py sonify.py imerg --no-video --sounds tracks/imerg/sounds_samples_demo.toml`.

Built-in instruments: `marimba`, `bell`, `pluck`, `sine` (notes), `pad` (chords),
`rumble`, `noise` (textures).

### Temperature, wind and other "field" tracks: a list of sounds

Their `sounds.toml` is a list: every `[[sound]]` block is one sound, and you can add,
remove or copy blocks freely. Each sound has a **kind** and, where it matters, a **range**
of values (in the track's units, e.g. °C or m/s):

| kind | follows | you hear |
|---|---|---|
| `voices` | the average value in 5 bands of latitude | 5 held notes; higher value = higher note |
| `hits` | places whose value is inside `range` | a short note each time; more area in range = more notes; west→east = left→right; value = pitch and loudness |
| `background` | the global average (`measure = "mean"`) or the share of the globe inside `range` (`measure = "area"`, optionally one `hemisphere`) | a looping texture whose volume follows it |
| `chime` | the start of every day | one note or chord |

For example, chimes for strong wind and a marimba for a fresh breeze:

```toml
[[sound]]
name = "chimes"
kind = "hits"
range = [20]          # 20 m/s and up
sample = "samples/wind-chimes.wav"
root = "A6"

[[sound]]
name = "breeze"
kind = "hits"
range = [8, 20]
instrument = "marimba"
```

Every setting has a default (`SOUND_DEFAULTS` in `jukebox/config.py`), so a sound only
needs the lines you want to change. The rain track still uses its own fixed set of layers
(`pad, drops, thunder, snow, chime`).

Handy options while tweaking:

| Option | What it does |
|---|---|
| `--no-video` | skip building the website video (faster) |
| `--only chimes,breeze` | hear only those sounds, by name (rain track: `pad, drops, thunder, snow, chime`) |
| `--stems` | also save each sound as its own WAV in `output/<name>/stems/` |
| `--sounds tracks/imerg/x.toml` | use another settings file, so you can keep several versions |
| `--seed 3` | a different random arrangement of the drops |
| `--reanalyze` | redo the video analysis (normally automatic when `track.toml` changes) |
| `--video path.mp4` | use a video from somewhere else |

When you're happy, run once **without** `--no-video` / `--only` to update the website.

## Run the website (and the studio)

```
py studio.py
```

Open http://localhost:8000. That's the jukebox exactly as it will look online, plus a
**studio** at http://localhost:8000/studio/ (there's also a link under the track list) for
adding and editing tracks without touching any files:

1. **New track**: pick a folder name, then upload the NASA video.
2. Fill in the title and description, the date and time on the first frame (with its time
   zone; it's converted to UTC), and drag boxes over logos and date stamps to ignore them.
3. Upload the color bar and type the values at its two ends. Switch to "Check what a color
   reads as" and move the mouse over the video to test it, or show the value map.
4. Add sounds (voices, hits, background, chime: the page explains each one); for each one,
   drag the two knobs on the color bar to set the range of values it follows. A knob at the
   end of the bar means "no limit" on that side.
5. **Preview the sound** builds just the soundtrack, with the sounds that have "Include in
   preview" ticked (all of them at first); the website isn't changed. **Publish to the
   jukebox** builds everything and adds the track to the site. A progress bar shows how far it is.

Required fields have a *. Anything missing is marked in red when you save. **Back to the
jukebox** opens the player straight away (the homepage's `#explore`), with this track picked.

**Save** writes `tracks/<name>/track.toml` and `sounds.toml`, the same files you can edit by
hand (saving rewrites them in a standard layout, so hand-written comments are replaced).
**Export** gives a zip of the track folder to send to a teammate; **Import a zip** adds one.
**Delete** moves the folder to `tracks/_deleted/` (not in git), so it can be brought back.
The rain track can be built, published and exported here, but its settings stay in its
.toml files.

The studio only runs on your own computer: it only answers requests from this computer.

## "Add your own" on the public website

On the public website the same page (`website/studio/`) is the **"+ Add your own track"**
link under the track list. There's no server there, so the page runs our Python in the
visitor's browser with [Pyodide](https://pyodide.org) (Python for the browser):

- It's the same form and the same code (`jukebox/web.py` uses `jukebox/studio_core.py`, like
  `studio.py`), so nothing was rewritten in JavaScript.
- The browser reads the video (Python in the browser can't decode MP4s) and hands each frame
  to Python. Everything stays in that browser (IndexedDB): nothing is uploaded anywhere, and
  nobody else sees it. Their tracks show up in *their* jukebox marked "(yours)".
- **Export** gives the same zip as the studio's export. If someone sends you a good one,
  **Import a zip** in your studio, add the video, and publish it for everyone.
- The first visit downloads about 35 MB (Python, NumPy, SciPy, OpenCV); the browser keeps it
  after that. Reading the video takes about as long as the video plays; after that, changing
  the sounds takes seconds.
- Differences from the studio: no graph, no combined video file (the jukebox plays the
  original video slowed down, in sync with the soundtrack), and only the built-in instruments
  plus samples the visitor uploads (the team's `samples/` folder isn't on the website).

The browser runs the code in `website/py/jukebox.zip`. `py studio.py` and `py sonify.py`
update it automatically when the Python code changed (it's identical when the code is, so git
only sees a change when there is one); commit it with the rest. To try the public version on
your computer, run `py -m http.server 8000` in `website/` (not the studio) and open
http://localhost:8000/studio/: without the studio server it switches to the browser version.

## Without the studio

Without the studio, the plain way still works: `cd website` then `py -m http.server 8000`.
(Opening `index.html` directly won't work, because browsers block loading `tracks.json` from a file.)

## The temperature track

Temperature covers the whole map, so it uses the list of sounds above (`jukebox/compose_field.py`):

| What you see                                        | What you hear                                  |
|-----------------------------------------------------|------------------------------------------------|
| Average temperature of 5 bands of latitude          | 5 held voices; 1 °C warmer = one note higher   |
| Places above 30 °C                                  | Plucks; hotter = higher and louder             |
| …where, west → east                                 | …left → right: they sweep right→left every day as afternoon heat follows the sun |
| Share of the Northern Hemisphere below freezing     | Wind that grows as winter comes                |
| A new day (midnight UTC)                            | Chime                                          |

Colors are turned into °C with NASA's own color bar image (`tracks/gmao_t2m/colorbar.png`,
from SVS page 5147). The bar is found in the image automatically, and only its two ends
(−40 and 40) are written in `track.toml`. The words in the daily captions ("Hottest",
"below freezing") are set there too (`caption_high`, `caption_low`, `caption_share`).

**Tricky color bars** (see `tracks/WindSpeed/track.toml`): on NASA's wind bar, calm air is
see-through (the map shows through) and the strongest winds are plain grey, the same as
the land. Settings that handle this: `unmatched_value` (what colors that aren't on the bar
count as), `ignore_above` / `ignore_below` in `colorbar` (leave part of the bar out) and
`color_space = "lab"` (compare colors the way they look).

## Add a new visualization

The easiest way is the studio (`py studio.py`, then **New track**; see above). By hand:

Two kinds of video work:
- **"field"**: a value everywhere on a flat world map (temperature, wind, sea surface
  temperature, …). Start from `tracks/gmao_t2m` or `tracks/WindSpeed`.
- **"categories"**: data only where something happens, with its color bar inside the
  video (rain, …). Start from `tracks/imerg`.

For a "field" video:
1. Copy the folder `tracks/WindSpeed` and give the copy a new name, e.g. `tracks/SeaSurface`
   (the name is used in commands and file names, so no spaces).
2. Put the NASA video in it, and replace `colorbar.png` with its color bar image (a
   screenshot of the bar is fine).
3. In `track.toml`, change the texts, the color bar's `min`/`max` and `units`,
   `start_time` and `hours_per_frame` (read the timestamps of the first two frames),
   the thresholds and the caption words. Optional: `ignore` boxes for logos or labels
   drawn on the map.
4. In `sounds.toml`, make your list of sounds: instruments, samples and ranges.
5. Run `py sonify.py SeaSurface` and check `output/SeaSurface/features.png`.

## Project structure

```
sonify.py            run the whole pipeline
studio.py            the website + the studio (add/edit tracks in the browser)
tracks/              one folder per visualization (track.toml, sounds.toml, colorbar, video)
samples/             instrument WAV files shared by all tracks
jukebox/
  tracks.py          reads a track folder (track.toml)
  config.py          reads the sound settings, with defaults
  video.py           reading frames
  palette.py         color bar → numbers (rain track: bar inside the video)
  colorbar.py        reads a color bar image (finds the bar automatically)
  features.py        numbers per frame (rain track)
  field.py           numbers per frame ("field" tracks: temperature, wind)
  ranges.py          "how much of the map is between X and Y" from those numbers
  timeline.py        frame → date and soundtrack time
  compose.py         the mapping from features to music (the "score", rain track)
  compose_field.py   the score for "field" tracks: the list of sounds
  instruments.py     built-in synths + loading/pitching/looping your WAV samples
  synth.py           low-level helpers (panning, pad tone, rumble, reverb)
  describe.py        accessible descriptions + CSV
  tomlwriter.py      writes track.toml / sounds.toml when the studio saves
  studio_core.py     the studio's logic (save, colors, uploads, export/import), for both versions
  web.py             the studio in a visitor's browser (run by Pyodide)
  webbundle.py       packs this folder into website/py/jukebox.zip for the browser
  plots.py           feature plots
website/             the jukebox site (static: HTML/CSS/JS)
  studio/            the Add / Edit track page (local studio and public "add your own")
  js/mytracks.js     visitors' own tracks, saved in their browser
  py/jukebox.zip     the Python code the browser runs (made automatically)
```

Visualizations: NASA Scientific Visualization Studio / Earth Information Center.
