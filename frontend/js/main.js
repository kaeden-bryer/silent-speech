// Bare test page: exercises the backend contract end to end. Track 1 replaces it with the
// real UI; keep calling the backend through api.js.

import { api } from "./api.js";

const $ = (id) => document.getElementById(id);
let stream = null;
let recorder = null;

api.health()
  .then((health) => {
    $("status").textContent = health.modules
      .map((m) => `${m.kind}: ${m.active}${m.fallback ? " (placeholder)" : ""}`)
      .join(" · ");
  })
  .catch(() => {
    $("status").textContent = "Backend offline";
  });

$("camera-btn").onclick = async () => {
  unlockSpeech();
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 }, frameRate: { ideal: 25 } },
    });
    $("preview").srcObject = stream;
    $("record-btn").disabled = false;
  } catch (err) {
    // navigator.mediaDevices is undefined on plain http (except localhost)
    $("result").textContent = `Camera error: ${err.message}. Phones need HTTPS (see README).`;
  }
};

$("record-btn").onclick = () => {
  unlockSpeech();
  if (recorder?.state === "recording") {
    recorder.stop();
    return;
  }
  const chunks = [];
  recorder = new MediaRecorder(stream);
  recorder.ondataavailable = (event) => chunks.push(event.data);
  recorder.onstop = () => {
    $("record-btn").textContent = "Record";
    send(api.sendVideo(new Blob(chunks, { type: recorder.mimeType })));
  };
  recorder.start();
  $("record-btn").textContent = "Stop";
};

$("text-form").onsubmit = (event) => {
  event.preventDefault();
  unlockSpeech();
  send(api.sendText($("text-input").value, $("fix-checkbox").checked));
};

async function send(request) {
  $("result").textContent = "…";
  try {
    const result = await request;
    $("result").textContent = JSON.stringify(result, null, 2);
    if (!result.text) return;
    // Contract with the TTS module: play audio_url if there is one, else use the browser voice.
    if (result.audio_url) {
      new Audio(api.audioUrl(result.audio_url)).play().catch(() => speak(result.text));
    } else {
      speak(result.text);
    }
  } catch (err) {
    $("result").textContent = err.message;
  }
}

function speak(text) {
  if ("speechSynthesis" in window) speechSynthesis.speak(new SpeechSynthesisUtterance(text));
}

// iOS only allows speech after a user gesture: speak something empty inside a tap once.
function unlockSpeech() {
  speak("");
}
