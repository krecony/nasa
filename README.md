# Earth Jukebox

NASA Earth visualizations turned into music: hear rain, wind, and temperature change
as you watch. Created for the NASA SpaceApps
[Earth Information Jukebox Challenge](https://www.spaceappschallenge.org/2026/challenges/the-earth-information-jukebox/).

**[Live website](https://krecony.github.io/nasa/)** ·
**[Open the jukebox](https://krecony.github.io/nasa/#explore)** ·
**[Create a track](https://krecony.github.io/nasa/studio/)** ·
[Source code](https://github.com/krecony/nasa)

<video src="media/demo.mp4" controls width="100%">
  <a href="media/demo.mp4">Watch the demo</a>
</video>

## What it does

An interactive WebGL forest leads into a video jukebox with three published tracks:

| Track | What you hear |
| --- | --- |
| Global Rain and Snow (IMERG) | Rain as plucks, heavy downpours as thunder, snow as bells |
| Near-Surface Wind Speed (GEOS-FP) | Wind speed as whistles, storms as wind chimes |
| Near-Surface Temperature (GEOS-FP) | Temperature as held voices, heat as plucks, freezing areas as wind |

The Python pipeline reads video frames, maps colors back to values using the
visualization's legend, and converts those values into pitch, volume, rhythm, and
stereo position. It generates a soundtrack, feature plots/CSV, daily captions, and
a video with the music. Captions start off; enable them in the video controls.

The public studio runs the Python engine in your browser through Pyodide. Custom
tracks stay in that browser's storage and appear in your jukebox; export/import
ZIP files to share them. Processing happens locally, with no video uploads.

## Run locally

For the website alone, serve the included media without installing Python packages:

```sh
python3 -m http.server 8000 --directory website
```

Open [localhost:8000](http://localhost:8000). The studio uses browser processing in
this mode.

For the local studio and track generation, use **Python 3.11+** and install
**FFmpeg** on your PATH to build videos:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python studio.py
```

On Windows, create the environment with `py -m venv .venv` and activate it with
`.venv\Scripts\Activate.ps1` in PowerShell.

Open [the local studio](http://localhost:8000/studio/) to add a NASA video, define
its color scale, choose sounds, preview, and publish to the local website. This
mode saves tracks to disk. The form edits wind/temperature-style field tracks;
the rain track's settings are edited in TOML.

## Build or customize tracks

Bulding new tracks and customizing new ones can be done using the web app by running the studio, 
or by manually using `sonify.py`.

Each folder in [`tracks/`](tracks/) contains `track.toml` (metadata, video, color
scale, timing) and `sounds.toml` (instruments and data-to-sound mappings). Put the
original video in that folder, or use `--video path/to/video.mp4`; source videos
are excluded from Git. See [`samples/README.md`](samples/README.md) for WAV instruments.

```sh
python sonify.py --list
python sonify.py WindSpeed                 # build and update the local website
python sonify.py --all                     # build every configured track
python sonify.py WindSpeed --no-publish    # preview without changing the website
```

Results go to `output/<track>/`; published media goes to `website/media/` and
`website/tracks.json`. Analysis is cached; use `--reanalyze` to force extraction,
`--stems` for individual sound layers, or `--help` for all options.

## Code and deployment

- [`website/`](website/): static HTML/CSS/JavaScript, WebGL forest, player, and browser studio.
- [`jukebox/`](jukebox/): shared analysis, synthesis, captions, and studio logic.
- [`studio.py`](studio.py): local HTTP server and studio API.
- [`sonify.py`](sonify.py): flat-map track generation.
- [`tracks/`](tracks/) and [`samples/`](samples/): track configuration and instrument audio.

Visualizations: NASA Scientific Visualization Studio / Earth Information Center.
