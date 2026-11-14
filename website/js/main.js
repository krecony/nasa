// Earth Jukebox website: loads tracks.json (written by sonify.py) and plays them.

const $ = (id) => document.getElementById(id);
const video = $('video');
const captions = $('captions');
const playButton = $('play');
const announce = $('announce');
const status = $('status');

let tracks = [];

async function init() {
  try {
    const res = await fetch('tracks.json');
    tracks = await res.json();
  } catch (err) {
    $('track-title').textContent = 'Could not load tracks.json';
    status.textContent = 'Run the site through a local server (see README), and run sonify.py first.';
    return;
  }

  const list = $('track-list');
  for (const track of tracks) {
    const li = document.createElement('li');
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = track.title;
    btn.dataset.id = track.id;
    btn.setAttribute('aria-pressed', 'false');
    btn.addEventListener('click', () => selectTrack(track.id, true));
    li.append(btn);
    list.append(li);
  }

  const fromUrl = new URLSearchParams(location.search).get('track');
  selectTrack(tracks.some((t) => t.id === fromUrl) ? fromUrl : tracks[0]?.id, false);
}

function selectTrack(id, autoplay) {
  const track = tracks.find((t) => t.id === id);
  if (!track) return;

  for (const btn of document.querySelectorAll('#track-list button')) {
    btn.setAttribute('aria-pressed', String(btn.dataset.id === id));
  }

  $('track-title').textContent = track.title;
  $('track-source').textContent = track.source;
  $('description').textContent = track.description;
  $('features-image').src = track.features_image;

  const guide = $('guide');
  guide.replaceChildren(...track.listening_guide.map((line) => {
    const li = document.createElement('li');
    li.textContent = line;
    return li;
  }));

  status.textContent = '';
  if (!track.video) {
    status.textContent = 'No video yet for this track: run sonify.py with ffmpeg installed.';
    return;
  }
  video.src = track.video;
  captions.src = track.captions;
  captions.track.mode = 'showing';
  if (autoplay) video.play();
}

// Play / pause button (the native video controls work too)
playButton.addEventListener('click', () => (video.paused ? video.play() : video.pause()));
video.addEventListener('play', () => {
  playButton.textContent = 'Pause';
  playButton.setAttribute('aria-pressed', 'true');
});
video.addEventListener('pause', () => {
  playButton.textContent = 'Play';
  playButton.setAttribute('aria-pressed', 'false');
});

// Send each day's description to the live region so screen readers read it
captions.addEventListener('cuechange', () => {
  const cue = captions.track.activeCues?.[0];
  if (cue && announce.checked && !video.paused) status.textContent = cue.text;
});

init();
