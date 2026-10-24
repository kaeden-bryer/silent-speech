"""Correction: noisy lip reader text + conversation context -> what the user meant.  (Track 3)

Select with CORRECTION=<name> in backend/.env. To add an implementation, create a file
with a TextCorrector subclass (see base.py) and register it here, e.g.
    "llm": ".llm:LLMCorrector",
"""

IMPLEMENTATIONS = {
    "passthrough": ".passthrough:Passthrough",
}
FALLBACK = "passthrough"
