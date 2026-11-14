# Your own instruments

Put WAV files here and point to them from a sound settings file (`sounds/*.toml`):

```toml
[drops]
sample = "samples/my_piano_C4.wav"
root = "C4"          # the note the recording plays
```

Then run `py sonify.py imerg videos/imergert_1080p_30.mp4 --no-video` and listen.

## What works best

| Layer           | Good samples                                   | Notes                                              |
|-----------------|------------------------------------------------|----------------------------------------------------|
| `drops`, `snow`, `chime` | One short note: piano, kalimba, harp, glockenspiel, a water drip, a tapped glass | Played at many pitches. Set `root` to its note. `pitched = false` plays it unchanged (drums, drips). `length = 0.6` cuts long ones short. |
| `pad`           | One long, steady note: strings, organ, choir "aah", synth pad | Looped to fill each day and pitched to the chord. |
| `thunder` texture | Any recording: rain, thunder, wind, waves     | Looped; its volume follows how much heavy rain there is. |
| `thunder` boom  | A single thunderclap, drum hit                 | `boom_sample = "samples/....wav"`                  |

- **Format:** WAV (16-bit, 24-bit or float), mono or stereo, any sample rate. MP3 won't
  work: convert it first, e.g. `ffmpeg -i in.mp3 out.wav`.
- **Start:** silence at the start is trimmed automatically.
- **Don't know the note?** Use a tuner app, or just try `root` values until it sounds in
  tune with the chord pad.
- Pitching works by changing the playback speed, like a record player. Large jumps (more
  than about an octave from `root`) sound chipmunk-y or muddy. If you can, record near the
  middle of the range you use (`lowest_note`/`highest_note`).

## Where to get samples

- Record your own on a phone, then export as WAV.
- [freesound.org](https://freesound.org): free, but check each file's license (CC0 is
  easiest; CC-BY means you must credit the author on your site).
- [Philharmonia sound samples](https://philharmonia.co.uk/audio-sound-samples/): free
  single notes of orchestral instruments, with the note in the file name. They're MP3s,
  so convert them to WAV first.

## Included examples (made with code, free to use)

- `example_kalimba_C5.wav`: a kalimba-like note, root C5. Try it for `drops`.
- `example_rain_loop.wav`: a rain hiss texture. Try it as the `thunder` texture.

`sounds/imerg_samples_demo.toml` uses both:

```
py sonify.py imerg videos/imergert_1080p_30.mp4 --no-video --sounds sounds/imerg_samples_demo.toml
```
