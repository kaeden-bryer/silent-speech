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
  sendText: (text, voice) => request("/api/text", json({ text, voice })),

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
// What the phone does with the sound is reported back, and printed in the server's terminal.
let report = () => {};
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
  report = (message) => send(JSON.stringify({ type: "log", message }));
  return {
    ready: () => ws.readyState === WebSocket.OPEN,
    start: (voice) => send(JSON.stringify({ type: "start", voice })),
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

// result.audio is base64 WAV (or MP3), or null -> speak result.text with the browser voice.
// onEnd fires when playback finishes (or immediately if nothing can play).
export function play(result, { onEnd } = {}) {
  if (result.audio) {
    player.onended = player.onerror = () => onEnd?.();
    player.src = `data:audio/${result.audio.startsWith("UklGR") ? "wav" : "mpeg"};base64,${result.audio}`;
    player.play().then(
      () => report(`voice: <audio> element, "${result.text}"`),
      (err) => {
        report(`voice: <audio> refused (${err.name}), browser voice instead, "${result.text}"`);
        speak(result.text, { onEnd });
      },
    );
  } else {
    report(`voice: no audio from the server, browser voice, "${result.text}"`);
    speak(result.text, { onEnd });
  }
}

// Groups of words arrive one after another. With Web Audio each one is set to start the
// moment the one before ends: no gap, no start-up delay. The <audio> player is the fallback.
let context = null;
let playEnd = 0; // when the last piece set to play ends (Web Audio time)
let decoding = Promise.resolve(); // keeps the pieces in order while they are decoded

function sound() {
  const Context = window.AudioContext || window.webkitAudioContext;
  if (!context && Context) {
    context = new Context();
    if (navigator.audioSession) navigator.audioSession.type = "playback"; // iPhones: play even on silent
  }
  return context;
}

export function playInOrder(piece, { onEnd } = {}) {
  const ctx = sound();
  if (!piece.audio || ctx?.state !== "running") {
    if (piece.audio) report(`voice: Web Audio ${ctx ? ctx.state : "missing"}, trying <audio>`);
    return void playQueued(piece, { onEnd });
  }
  decoding = decoding
    .then(() => ctx.decodeAudioData(Uint8Array.from(atob(piece.audio), (c) => c.charCodeAt(0)).buffer))
    .then((buffer) => {
      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(ctx.destination);
      source.onended = () => onEnd?.();
      const at = Math.max(ctx.currentTime + 0.005, playEnd);
      source.start(at);
      playEnd = at + buffer.duration;
      const session = navigator.audioSession ? navigator.audioSession.type : "no audioSession API";
      report(`voice: Web Audio (${session}), ${buffer.duration.toFixed(2)}s "${piece.text}" [${piece.emotion}]`);
    })
    .catch((err) => {
      report(`voice: Web Audio failed (${err}), trying <audio>`);
      playQueued(piece, { onEnd });
    });
}

// The <audio> way: one piece after the other, never on top of each other.
let queue = Promise.resolve();
function playQueued(piece, { onEnd } = {}) {
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
  const ctx = sound();
  if (ctx && ctx.state !== "running") {
    ctx.resume();
    const blank = ctx.createBufferSource(); // a sound started during the tap is what unlocks it
    blank.buffer = ctx.createBuffer(1, 1, 22050);
    blank.connect(ctx.destination);
    blank.start();
  }
  if (unlocked || !player.paused) return; // once is enough, and doing it again would cut off a sentence
  player.src = SILENCE;
  player.play().then(() => (unlocked = true), () => {}); // refused outside a tap: try again at the next one
}
