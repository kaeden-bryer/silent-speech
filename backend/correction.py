"""Track 3: fix the lip reader's mistakes.

Input:  raw_text  the lip reader's guess, e.g. "can i half a coffee wiz oat milk"
        history   the conversation so far, oldest first:
                  [{"speaker": "me", "text": "..."}, {"speaker": "them", "text": "..."}]
Output: what the user meant, e.g. "Can I have a coffee with oat milk?"
"""


def correct(raw_text: str, history: list[dict]) -> str:
    # TODO: ask a fast AI model to fix raw_text, using the history as context
    return raw_text
