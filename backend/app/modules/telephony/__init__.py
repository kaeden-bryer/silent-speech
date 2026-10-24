"""Phone calls: the user talks to someone over a real phone line.  (Track 4, optional)

Select with TELEPHONY=<name> in backend/.env. To add an implementation, create a file
with a Telephony subclass (see base.py) and register it here, e.g.
    "twilio": ".twilio:TwilioTelephony",
"""

IMPLEMENTATIONS = {
    "disabled": ".disabled:DisabledTelephony",
}
FALLBACK = "disabled"
