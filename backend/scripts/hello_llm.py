"""SMA-16: call Gemini or Groq through the same OpenAI-compatible client.

Usage (from backend/, with the venv active):
    python scripts/hello_llm.py gemini
    python scripts/hello_llm.py groq
    python scripts/hello_llm.py gemini --temperature 1.0
    python scripts/hello_llm.py groq --list-models
"""

import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError

# The only differences between providers: where to send the request,
# which key to use, and which model to ask for.
PROVIDERS = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "key_env": "GEMINI_API_KEY",
        "model_env": "GEMINI_MODEL",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "model_env": "GROQ_MODEL",
    },
}

SYSTEM_PROMPT = (
    "You are a concise study assistant for college students. "
    "Answer in at most 3 sentences."
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Say hello to an LLM.")
    parser.add_argument("provider", choices=PROVIDERS.keys())
    parser.add_argument("--question", default="Explain Newton's second law with one everyday example.")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--list-models", action="store_true")
    args = parser.parse_args()

    # Load backend/.env no matter which folder the script is run from.
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    cfg = PROVIDERS[args.provider]
    api_key = os.getenv(cfg["key_env"])
    if not api_key:
        sys.exit(f"Missing {cfg['key_env']} in backend/.env")

    client = OpenAI(base_url=cfg["base_url"], api_key=api_key, timeout=60)

    if args.list_models:
        for model in client.models.list():
            print(model.id)
        return

    model = os.getenv(cfg["model_env"])
    if not model:
        sys.exit(f"Missing {cfg['model_env']} in backend/.env")

    # The "messages" list is the whole conversation the model sees.
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": args.question},
    ]

    start = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=args.temperature,
            max_tokens=1024,  # generous: some models "think" before answering
        )
    except RateLimitError:
        sys.exit("Rate limited (HTTP 429): free-tier limit reached. Wait a minute or try the other provider.")
    except APIConnectionError as e:
        sys.exit(f"Could not reach {args.provider}: {e}")
    except APIStatusError as e:
        sys.exit(f"{args.provider} returned HTTP {e.status_code}: {e.body}")
    elapsed = time.perf_counter() - start

    answer = response.choices[0].message.content or "(empty answer - try a higher max_tokens)"
    usage = response.usage

    print(f"\nProvider : {args.provider}")
    print(f"Model    : {model}")
    print(f"Temp     : {args.temperature}")
    print(f"Latency  : {elapsed:.2f} s")
    if usage:
        print(f"Tokens   : {usage.prompt_tokens} in, {usage.completion_tokens} out, {usage.total_tokens} total")
    print(f"\nAnswer:\n{answer}\n")


if __name__ == "__main__":
    main()