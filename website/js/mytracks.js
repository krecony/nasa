// The visitor's own tracks, saved only in this browser (IndexedDB).
// Written by the "add your own" page (studio/local.js), read by the jukebox (main.js).
//   tracks: { id, title, source, description, listening_guide, slow_down, duration, video_seconds, updated }
//   media:  "<id>/video" (the original video), "<id>/audio" (WAV), "<id>/captions" (WebVTT, video time)

const DB_NAME = 'earth-jukebox-mine';
let dbPromise = null;

function open() {
  if (!dbPromise) {
    dbPromise = new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains('tracks')) db.createObjectStore('tracks', { keyPath: 'id' });
        if (!db.objectStoreNames.contains('media')) db.createObjectStore('media');
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }
  return dbPromise;
}

async function run(store, mode, fn) {
  const db = await open();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(store, mode);
    const req = fn(tx.objectStore(store));
    tx.oncomplete = () => resolve(req?.result);
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error || new Error('Saving in the browser failed (is it full?).'));
  });
}

export const listTracks = () => run('tracks', 'readonly', (s) => s.getAll()).then((t) => t || []);
export const getTrack = (id) => run('tracks', 'readonly', (s) => s.get(id));
export const putTrack = (entry) => run('tracks', 'readwrite', (s) => s.put({ ...entry, updated: Date.now() }));
export const getMedia = (key) => run('media', 'readonly', (s) => s.get(key));
export const putMedia = (key, blob) => run('media', 'readwrite', (s) => s.put(blob, key));

export async function removeTrack(id) {
  await run('tracks', 'readwrite', (s) => s.delete(id));
  await run('media', 'readwrite', (s) => s.delete(IDBKeyRange.bound(`${id}/`, `${id}/￿`)));
}

// Ask the browser not to clear our storage when space runs low (it may still ask the visitor).
export function keepStorage() {
  try { navigator.storage?.persist?.(); } catch { /* not supported */ }
}
