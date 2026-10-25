// Every backend call lives here (contract: the API table in the root README).
// Paths are relative, so it works both through the Vite dev proxy and when the
// backend serves the built app itself.

const TIMEOUT_MS = 60_000; // give up rather than stay "thinking" forever

async function request(path, options = {}) {
  const response = await fetch(path, { signal: AbortSignal.timeout?.(TIMEOUT_MS), ...options });
  if (!response.ok) throw new Error(`${response.status}: ${await response.text()}`);
  return response.json();
}

const json = (body) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  // One recorded clip = one sentence -> {raw_text, text, emotion, audio}
  sendVideo(clip) {
    const form = new FormData();
    form.append("video", clip, clip.type.includes("mp4") ? "clip.mp4" : "clip.webm");
    return request("/api/video", { method: "POST", body: form });
  },

  // Typed text, used as if the lip reader had read it
  sendText: (text) => request("/api/text", json({ text })),

  // -> { history: [{speaker: "me" | "them", text}], call_active }
  history: () => request("/api/history"),

  call: (number) => request("/api/call", json({ number })),
  hangup: () => request("/api/hangup", { method: "POST" }),
};

// Live lip reading while a button is held (backend/streaming.py), over one WebSocket that
// reconnects by itself. `on` gets the server's messages by type:
//   heard({heard, pending, face})  after each reading: words said so far, words not sure yet
//   say({text, audio})             a group of sure words to voice, in order
//   done({text, emotion})          everything was said after the release
//   error({message}), status(connected)
export function connectLive(on) {
  let ws;
  let closed = false;
  function open() {
    ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/live`);
    ws.onopen = () => on.status?.(true);
    ws.onmessage = (e) => {
      const message = JSON.parse(e.data);
      on[message.type]?.(message);
    };
    ws.onclose = () => {
      on.status?.(false);
      if (!closed) setTimeout(open, 1000);
    };
  }
  open();
  const send = (data) => ws.readyState === WebSocket.OPEN && (ws.send(data), true);
  return {
    ready: () => ws.readyState === WebSocket.OPEN,
    start: () => send(JSON.stringify({ type: "start" })),
    stop: () => send(JSON.stringify({ type: "stop" })),
    // One camera frame: when it was shot (ms) + the JPEG. Skipped when the network falls
    // behind: a late frame is worth less than a missing one.
    frame(ms, jpeg) {
      if (ws.bufferedAmount > 2_000_000) return false;
      const data = new Uint8Array(8 + jpeg.byteLength);
      new DataView(data.buffer).setFloat64(0, ms, true);
      data.set(new Uint8Array(jpeg), 8);
      return send(data);
    },
    close() {
      closed = true;
      ws.close();
    },
  };
}

// One audio element for every sentence: iPhones only let an element play sound if
// it was first started during a tap, and the answer arrives seconds after the tap.
// unlockSound() starts it (silently) during the first tap.
const player = new Audio();
const SILENCE = "data:audio/wav;base64,UklGRjQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YRAAAAAAAAAAAAAAAAAAAAAAAAAA";
let unlocked = false;

// result.audio is base64 MP3, or null -> speak result.text with the browser voice.
// onEnd fires when playback finishes (or immediately if nothing can play).
export function play(result, { onEnd } = {}) {
  if (result.audio) {
    player.onended = player.onerror = () => onEnd?.();
    player.src = "data:audio/mpeg;base64," + result.audio;
    player.play().catch(() => speak(result.text, { onEnd }));
  } else {
    speak(result.text, { onEnd });
  }
}

// Groups of words arrive one after another: voice them in order, never on top of each other.
let queue = Promise.resolve();
export function playInOrder(piece, { onStart, onEnd } = {}) {
  queue = queue.then(
    () =>
      new Promise((done) => {
        let over = false;
        let timer;
        const finish = () => {
          if (over) return;
          over = true;
          clearTimeout(timer);
          onEnd?.();
          done();
        };
        timer = setTimeout(finish, 15_000); // one piece that never ends must not block the rest
        onStart?.();
        play(piece, { onEnd: finish });
      }),
  );
}

export function speak(text, { onEnd } = {}) {
  if (!("speechSynthesis" in window)) return void onEnd?.();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.onend = () => onEnd?.();
  speechSynthesis.speak(utterance);
}

// iPhones only allow sound after a tap: call this inside the first tap handler.
// Only a finger lifted (or a click) counts as a tap there: one touching down does not.
export function unlockSound() {
  speak("");
  if (unlocked || !player.paused) return; // once is enough, and doing it again would cut off a sentence
  player.src = SILENCE;
  player.play().then(() => (unlocked = true), () => {}); // refused outside a tap: try again at the next one
}
