import time
from threading import Thread

import torch
from transformers import TextIteratorStreamer, pipeline

model_id = "Qwen/Qwen2.5-1.5B-Instruct"

print("Loading the model... (Downloads ~3GB on first run)")

# We load in float16 to keep memory usage low for older GTX cards
pipe = pipeline(
    "text-generation",
    model=model_id,
    model_kwargs={"torch_dtype": torch.float16},
    device="cuda", # This forces the workload onto your GPU
)

# A fun prompt to test its personality and speed
messages = [
    {"role": "system", "content": "You are an author writing a short story."},
    {"role": "user", "content": "Write a science fiction story about an AI celebrity controlling the masses"},
]

print("\nThinking...")
streamer = TextIteratorStreamer(
    pipe.tokenizer,
    skip_prompt=True,
    skip_special_tokens=True,
)

generation_kwargs = {
    "text_inputs": messages,
    "streamer": streamer,
    "max_new_tokens": 50000,
}
generation_thread = Thread(target=pipe, kwargs=generation_kwargs)
start_time = time.perf_counter()
generation_thread.start()

print("\n--- Output ---\n")
first_token_time = None
token_count = 0
for text in streamer:
    if first_token_time is None:
        first_token_time = time.perf_counter()
    token_count += 1
    print(text, end="", flush=True)

generation_thread.join()
elapsed = time.perf_counter() - start_time
if first_token_time is not None:
    time_to_first_token = first_token_time - start_time
    print(
        f"\n\n--- Speed: {token_count} streamed chunks in {elapsed:.2f}s "
        f"({token_count / elapsed:.2f} chunks/s; "
        f"first chunk in {time_to_first_token:.2f}s) ---"
    )