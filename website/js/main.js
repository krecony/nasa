// Earth Jukebox website: loads tracks.json (written by sonify.py) and plays them.
// Also lists the visitor's own tracks ("add your own", saved only in their browser by studio/local.js):
// those play the original video slowed down, with their soundtrack in sync.

import * as Mine from './mytracks.js';

const $ = (id) => document.getElementById(id);
const video = $('video');
const captions = $('captions');
const playButton = $('play');
const status = $('status');

let tracks = [];
let local = null;   // the visitor's track that's playing: { audio, slow, urls }

async function init() {
  try {
    const res = await fetch('tracks.json');
    tracks = await res.json();
  } catch (err) {
    $('track-title').textContent = 'Could not load tracks.json';
    status.textContent = 'Run the site through a local server (see README), and run sonify.py first.';
    return;
  }
  tracks.forEach(addButton);

  const fromUrl = new URLSearchParams(location.search).get('track');
  selectTrack(tracks.some((t) => t.id === fromUrl) ? fromUrl : tracks[0]?.id, false);

  // the visitor's own tracks are added when the browser's storage answers (it can take a moment)
  try {
    const mine = (await Mine.listTracks()).map((t) => ({ ...t, id: `mine:${t.id}`, mineId: t.id, local: true }));
    tracks = tracks.concat(mine);
    mine.forEach(addButton);
  } catch { /* this browser can't store anything: just our tracks */ }
}

function addButton(track) {
  const li = document.createElement('li');
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.textContent = track.local ? `${track.title} (yours)` : track.title;
  if (track.local) btn.title = 'Your own track, saved only in this browser';
  btn.dataset.id = track.id;
  btn.setAttribute('aria-pressed', 'false');
  btn.addEventListener('click', () => selectTrack(track.id, true));
  li.append(btn);
  $('track-list').append(li);
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
  const graph = $('features-image');
  graph.hidden = !track.features_image;
  if (track.features_image) graph.src = track.features_image;
  stopLocal();

  const guide = $('guide');
  guide.replaceChildren(...track.listening_guide.map((line) => {
    const li = document.createElement('li');
    li.textContent = line;
    return li;
  }));

  status.textContent = '';
  if (track.local) return playLocal(track, autoplay);
  if (!track.video) {
    status.textContent = 'No video yet for this track: run sonify.py with ffmpeg installed.';
    return;
  }
  video.src = track.video;
  captions.src = track.captions;
  // Start with subtitles hidden; users can enable them through the video controls.
  captions.track.mode = 'hidden';
  if (autoplay) video.play();
}

// ---- the visitor's own tracks: original video, slowed down, with the soundtrack in sync

function stopLocal() {
  if (!local) return;
  local.audio.pause();
  local.urls.forEach((u) => URL.revokeObjectURL(u));
  local = null;
  video.loop = true;
  video.defaultPlaybackRate = video.playbackRate = 1;
}

async function playLocal(track, autoplay) {
  const [vid, wav, vtt] = await Promise.all(['video', 'audio', 'captions'].map((k) => Mine.getMedia(`${track.mineId}/${k}`)));
  if (!vid || !wav) {
    status.textContent = 'This track isn\'t finished: open it in “Add your own” and press “Add to my jukebox”.';
    return;
  }
  const [videoUrl, audioUrl, vttUrl] = [vid, wav, vtt].map((b) => (b ? URL.createObjectURL(b) : ''));
  const audio = new Audio(audioUrl);
  audio.preload = 'auto';
  local = { audio, slow: track.slow_down || 1, urls: [videoUrl, audioUrl, vttUrl].filter(Boolean) };
  // the soundtrack can run a little past the video's end (reverb); then both start again
  audio.addEventListener('ended', () => { if (local?.audio === audio) { video.currentTime = 0; video.play(); } });
  video.loop = false;
  video.defaultPlaybackRate = 1 / local.slow;
  video.src = videoUrl;
  video.playbackRate = 1 / local.slow;
  captions.src = vttUrl;
  captions.track.mode = 'hidden';
  if (autoplay) video.play();
}

const soundtrackTime = () => Math.min(video.currentTime * local.slow, local.audio.duration || Infinity);
video.addEventListener('play', () => { if (local) { local.audio.currentTime = soundtrackTime(); local.audio.play(); } });
video.addEventListener('pause', () => { if (local && !video.ended) local.audio.pause(); });
// while the video jumps (can take a moment), the soundtrack waits at the new spot
video.addEventListener('seeking', () => { if (local) { local.audio.pause(); local.audio.currentTime = soundtrackTime(); } });
video.addEventListener('seeked', () => {
  if (!local) return;
  local.audio.currentTime = soundtrackTime();
  if (!video.paused) local.audio.play();
});
video.addEventListener('timeupdate', () => {
  if (local && !video.paused && !video.seeking && Math.abs(local.audio.currentTime - soundtrackTime()) > 0.3) local.audio.currentTime = soundtrackTime();
});
video.addEventListener('volumechange', () => { if (local) { local.audio.volume = video.volume; local.audio.muted = video.muted; } });

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

init();
