// Every backend call lives here (contract: the API table in the root README).
// Paths are relative, so it works both through the Vite dev proxy and when the
// backend serves the built app itself.

async function request(path, options = {}) {
  const response = await fetch(path, options);
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

// result.audio is base64 MP3, or null -> speak result.text with the browser voice.
// onEnd fires when playback finishes (or immediately if nothing can play).
export function play(result, { onEnd } = {}) {
  if (result.audio) {
    const audio = new Audio("data:audio/mpeg;base64," + result.audio);
    audio.onended = () => onEnd?.();
    audio.play().catch(() => speak(result.text, { onEnd }));
  } else {
    speak(result.text, { onEnd });
  }
}

export function speak(text, { onEnd } = {}) {
  if (!("speechSynthesis" in window)) return void onEnd?.();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.onend = () => onEnd?.();
  speechSynthesis.speak(utterance);
}

// iPhones only allow sound after a tap: call this inside the first tap handler.
export function unlockSound() {
  speak("");
}
