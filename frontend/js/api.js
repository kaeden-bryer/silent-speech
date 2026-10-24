// The frontend <-> backend contract. Every backend call goes through here.
// Shapes are documented in the root README and live at <backend>/docs.

// Empty = same origin (the backend serves this page). To use a backend elsewhere,
// open the page once with ?api=https://your-tunnel.example.com (remembered; ?api= resets).
const params = new URLSearchParams(location.search);
if (params.has("api")) store("apiBase", params.get("api"));
export const API_BASE = (store("apiBase") || "").replace(/\/+$/, "");

// One conversation = one session id. The backend keeps its history (context for the corrector).
let sessionId = store("sessionId");
if (!sessionId) newSessionId();

export function getSessionId() {
  return sessionId;
}

export function newSessionId() {
  sessionId = crypto.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  store("sessionId", sessionId);
  return sessionId;
}

async function request(path, { timeoutMs = 60000, ...options } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(API_BASE + path, { ...options, signal: controller.signal });
    if (!response.ok) throw new Error(`${response.status}: ${await response.text()}`);
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}

function postJson(body) {
  return { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

export const api = {
  // -> { ok, modules: [{ kind, requested, active, fallback, error }] }
  health: () => request("/api/health", { timeoutMs: 4000 }),

  // clip: Blob from MediaRecorder (one sentence, video only) -> UtteranceResult
  sendVideo(clip) {
    const form = new FormData();
    form.append("session_id", sessionId);
    form.append("video", clip, clip.type.includes("mp4") ? "clip.mp4" : "clip.webm");
    return request("/api/utterance/video", { method: "POST", body: form });
  },

  // Typed text, treated as lip reader output -> UtteranceResult
  sendText: (text, correct = true) => request("/api/utterance/text", postJson({ session_id: sessionId, text, correct })),

  // -> { session_id, turns: [{ speaker: "user" | "other", text, timestamp }], call_active }
  getSession: () => request(`/api/session/${encodeURIComponent(sessionId)}`),

  // Phone calls: 503 while telephony is on its placeholder
  startCall: (to) => request("/api/call/start", postJson({ session_id: sessionId, to })),
  hangUp: () => request("/api/call/hangup", postJson({ session_id: sessionId })),

  // UtteranceResult.audio_url is a backend path; null means "speak result.text with the browser voice"
  audioUrl: (path) => API_BASE + path,
};

function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    if (value) localStorage.setItem(key, value);
    else localStorage.removeItem(key);
  } catch {
    return null; // storage blocked (private mode): settings just don't persist
  }
}
