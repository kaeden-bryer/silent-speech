// App settings: one localStorage-backed store, readable from any component.
// Call-channel settings (captions, openingLine, filler) persist but do nothing
// until the call screen returns (see FEATURES.md).

import { useSyncExternalStore } from "react";

const KEY = "settings";
const DEFAULTS = {
  theme: "light", // "light" | "dark"
  textScale: 1, // multiplies the root font size (0.85–1.3)
  autoSpeak: true, // speak as soon as a confident result arrives
  confirmNumbers: true, // results containing digits wait for a tap
  smoothing: "light", // "off" = speak the raw lip-reading | "light" | "full"
  captions: true,
  openingLine: true,
  filler: false,
};

let state = { ...DEFAULTS };
try {
  state = { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) ?? "{}") };
} catch {
  // storage blocked (private mode): settings just don't persist
}

const listeners = new Set();

export function getSettings() {
  return state;
}

export function updateSettings(patch) {
  state = { ...state, ...patch };
  try {
    localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    /* see above */
  }
  listeners.forEach((notify) => notify());
}

export function useSettings() {
  const settings = useSyncExternalStore(
    (notify) => (listeners.add(notify), () => listeners.delete(notify)),
    () => state,
  );
  return [settings, updateSettings];
}
