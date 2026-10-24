"""Lip reading: silent video clip -> raw, noisy text.  (Track 2)

Select with LIPREADING=<name> in backend/.env. To add an implementation, create a file
with a LipReader subclass (see base.py) and register it here, e.g.
    "auto_avsr": ".auto_avsr:AutoAVSRLipReader",
"""

IMPLEMENTATIONS = {
    "mock": ".mock:MockLipReader",
}
FALLBACK = "mock"  # used when the selected implementation is missing or fails to load
