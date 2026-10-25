// Practice mode logic, kept pure so it can be unit-tested (practice.test.js).
// The screen (screens/Practice.jsx) drives this with useReducer.

// Practice phrases, grounded in how people actually (re)learn to be understood:
// - warm-ups are classic lipreading drill phrases (short, known shapes)
// - daily needs mirror first-focus AAC functional phrases (help, water, pain,
//   bathroom, medicine)
// - phone calls are the #1 barrier in the team's research brief
// - tricky shapes drill viseme-confusable sounds: p/b/m share one mouth shape,
//   f/v another — exaggerating those is the core lipreading skill
// 3–8 words each; everyday vocabulary the lip-reading model knows.
export const PHRASES = [
  // warm-up
  { text: "Hello, how are you?", category: "warm-up" },
  { text: "Thank you very much.", category: "warm-up" },
  { text: "Nice to meet you.", category: "warm-up" },
  { text: "See you later.", category: "warm-up" },
  // daily needs
  { text: "I need some help.", category: "daily needs" },
  { text: "Can I have some water?", category: "daily needs" },
  { text: "Where is the bathroom?", category: "daily needs" },
  { text: "I need my medicine.", category: "daily needs" },
  { text: "I am very tired.", category: "daily needs" },
  // phone calls
  { text: "Can you repeat that?", category: "phone calls" },
  { text: "One moment, please.", category: "phone calls" },
  { text: "My name is Cara.", category: "phone calls" },
  { text: "I want to make an appointment.", category: "phone calls" },
  // out and about
  { text: "I need more caffeine.", category: "out & about" },
  { text: "How much does it cost?", category: "out & about" },
  { text: "Have a great day!", category: "out & about" },
  // tricky mouth shapes (p/b/m and f/v drills)
  { text: "Pass me my purple pen.", category: "tricky shapes" },
  { text: "Bring back my big book.", category: "tricky shapes" },
  { text: "Five fresh vans move fast.", category: "tricky shapes" },
  { text: "My mouth makes many words.", category: "tricky shapes" },
];

// "caffeine." and "Caffeine" are the same word: compare letters only.
const normalize = (word) => word.toLowerCase().replace(/[^\p{L}\p{N}']/gu, "");

// Per-position comparison of the recognized phrase against the target.
// Punctuation stays attached to its word and never counts as a word.
export function diffWords(target, recognized) {
  const targetWords = target.split(/\s+/).filter(Boolean);
  const readWords = (recognized ?? "").split(/\s+/).filter(Boolean);
  const tokens = targetWords.map((word, i) => {
    const read = readWords[i] ?? null;
    const matched = read !== null && normalize(read) === normalize(word);
    return { word, read, matched };
  });
  const matched = tokens.filter((t) => t.matched).length;
  return {
    tokens,
    matched,
    total: targetWords.length,
    percent: Math.round((matched / targetWords.length) * 100),
    perfect: matched === targetWords.length,
  };
}

// ready -> recording -> processing -> result, plus error states that fall
// back to ready. Retry keeps the phrase; next advances and clears the result.
export const initialState = {
  phase: "ready", // "ready" | "recording" | "processing" | "result"
  phraseIndex: 0,
  result: null, // { score: diffWords(...), recognized, source: "lipread" | "typed" | "demo" }
  error: null, // { kind: "camera" | "recognition" | "service", message }
};

export function practiceReducer(state, event) {
  switch (event.type) {
    case "RECORD_START":
      return { ...state, phase: "recording", result: null, error: null };
    case "RECORD_STOP":
      return state.phase === "recording" ? { ...state, phase: "processing" } : state;
    case "PROCESS": // typed path goes straight to processing
      return { ...state, phase: "processing", result: null, error: null };
    case "RESULT": {
      const target = PHRASES[state.phraseIndex].text;
      return {
        ...state,
        phase: "result",
        error: null,
        result: {
          score: diffWords(target, event.recognized),
          recognized: event.recognized,
          source: event.source,
        },
      };
    }
    case "ERROR":
      return {
        ...state,
        phase: "ready",
        result: null,
        error: { kind: event.kind, message: event.message },
      };
    case "RETRY": // same phrase, clean slate
      return { ...state, phase: "ready", result: null, error: null };
    case "NEXT": // advance once, clear the prior result
      return {
        ...state,
        phase: "ready",
        result: null,
        error: null,
        phraseIndex: (state.phraseIndex + 1) % PHRASES.length,
      };
    default:
      return state;
  }
}
