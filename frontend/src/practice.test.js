import { describe, expect, it } from "vitest";
import { PHRASES, diffWords, initialState, practiceReducer } from "./practice.js";

describe("diffWords", () => {
  it("scores the spec example: 3 of 4, 75%, not perfect", () => {
    const score = diffWords("I need more caffeine.", "I need more coffee.");
    expect(score.total).toBe(4); // punctuation is not a separate word
    expect(score.matched).toBe(3);
    expect(score.percent).toBe(75);
    expect(score.perfect).toBe(false);
    expect(score.tokens[3]).toEqual({ word: "caffeine.", read: "coffee.", matched: false });
  });

  it("scores a perfect attempt: 4 of 4, 100%", () => {
    const score = diffWords("I need more caffeine.", "I need more caffeine.");
    expect(score.matched).toBe(4);
    expect(score.percent).toBe(100);
    expect(score.perfect).toBe(true);
  });

  it("ignores case and punctuation when matching", () => {
    const score = diffWords("Hello, how are you?", "hello How are YOU");
    expect(score.perfect).toBe(true);
  });

  it("marks missing trailing words as missed with no read alternative", () => {
    const score = diffWords("I need some help.", "I need");
    expect(score.matched).toBe(2);
    expect(score.tokens[2]).toEqual({ word: "some", read: null, matched: false });
    expect(score.tokens[3]).toEqual({ word: "help.", read: null, matched: false });
  });

  it("handles an empty recognition as zero matches", () => {
    const score = diffWords("See you later.", "");
    expect(score.matched).toBe(0);
    expect(score.percent).toBe(0);
  });

  it("keeps the denominator at the target word count when extra words are read", () => {
    const score = diffWords("See you later.", "see you later alligator");
    expect(score.total).toBe(3);
    expect(score.matched).toBe(3);
    expect(score.perfect).toBe(true);
  });
});

describe("practiceReducer", () => {
  const recorded = practiceReducer(initialState, { type: "RECORD_START" });

  it("walks ready -> recording -> processing -> result", () => {
    expect(initialState.phase).toBe("ready");
    expect(recorded.phase).toBe("recording");
    const processing = practiceReducer(recorded, { type: "RECORD_STOP" });
    expect(processing.phase).toBe("processing");
    const done = practiceReducer(processing, { type: "RESULT", recognized: "hello how are you", source: "lipread" });
    expect(done.phase).toBe("result");
    expect(done.result.score.total).toBe(PHRASES[0].text.split(" ").length);
  });

  it("ignores RECORD_STOP when not recording", () => {
    expect(practiceReducer(initialState, { type: "RECORD_STOP" })).toBe(initialState);
  });

  it("RETRY resets the attempt without advancing the phrase", () => {
    const done = practiceReducer(recorded, { type: "RESULT", recognized: "x", source: "typed" });
    const retried = practiceReducer(done, { type: "RETRY" });
    expect(retried.phase).toBe("ready");
    expect(retried.result).toBeNull();
    expect(retried.phraseIndex).toBe(done.phraseIndex);
  });

  it("NEXT advances exactly once and clears the prior result", () => {
    const done = practiceReducer(recorded, { type: "RESULT", recognized: "x", source: "typed" });
    const next = practiceReducer(done, { type: "NEXT" });
    expect(next.phraseIndex).toBe(done.phraseIndex + 1);
    expect(next.result).toBeNull();
    expect(next.phase).toBe("ready");
  });

  it("NEXT wraps around the end of the phrase list", () => {
    const atEnd = { ...initialState, phraseIndex: PHRASES.length - 1 };
    expect(practiceReducer(atEnd, { type: "NEXT" }).phraseIndex).toBe(0);
  });

  it("ERROR returns to ready with a message, clearing any result", () => {
    const done = practiceReducer(recorded, { type: "RESULT", recognized: "x", source: "typed" });
    const errored = practiceReducer(done, { type: "ERROR", kind: "camera", message: "denied" });
    expect(errored.phase).toBe("ready");
    expect(errored.result).toBeNull();
    expect(errored.error).toEqual({ kind: "camera", message: "denied" });
  });

  it("every phrase has 3-8 words and a category", () => {
    for (const p of PHRASES) {
      const words = p.text.split(/\s+/).length;
      expect(words).toBeGreaterThanOrEqual(3);
      expect(words).toBeLessThanOrEqual(8);
      expect(p.category).toBeTruthy();
    }
  });
});
