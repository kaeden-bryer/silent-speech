"""Try a corrector on its own, without the server (defaults to CORRECTION from .env):

    python -m app.modules.correction "can i half a coffee wiz oat milk"
    python -m app.modules.correction "yes too sugars" --context "Would you like sugar?"
"""

import argparse
import time

from app.config import Settings
from app.loader import instantiate
from app.schemas import ConversationContext, Turn

from . import IMPLEMENTATIONS

parser = argparse.ArgumentParser(description="Run one correction implementation on a sentence.")
parser.add_argument("text", help="noisy lip reader output")
parser.add_argument("--impl", default=Settings().correction, choices=IMPLEMENTATIONS)
parser.add_argument("--context", nargs="*", default=[], help="what the other person said before")
args = parser.parse_args()

corrector = instantiate(__package__, IMPLEMENTATIONS[args.impl])
corrector.load()
context = ConversationContext(turns=[Turn(speaker="other", text=t) for t in args.context])
start = time.perf_counter()
print(corrector.correct(args.text, context))
print(f"{(time.perf_counter() - start) * 1000:.0f} ms")
