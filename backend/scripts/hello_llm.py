"""SMA-16/17: ask one question to a model from the registry.

Run from backend/ with the venv active:
    python -m scripts.hello_llm gemini
    python -m scripts.hello_llm groq --temperature 1
    python -m scripts.hello_llm gemini --model gemini-3.5-flash
    python -m scripts.hello_llm groq --list-models
"""

import argparse
import sys
import time

from openai import APIConnectionError, APIStatusError, RateLimitError

from app.services.llm.registry import client_for, enabled_models, load_registry

SYSTEM_PROMPT = "You are a concise study assistant for college students. Answer in at most 3 sentences."


def main() -> None:
    registry = load_registry()
    parser = argparse.ArgumentParser(description="Say hello to an LLM.")
    parser.add_argument("provider", choices=registry["providers"].keys())
    parser.add_argument("--model", help="model id from models.yaml (default: first enabled for the provider)")
    parser.add_argument("--question", default="Explain Newton's second law with one everyday example.")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--list-models", action="store_true")
    args = parser.parse_args()

    try:
        client = client_for(registry, args.provider)
    except RuntimeError as e:
        sys.exit(str(e))

    if args.list_models:
        for m in client.models.list():
            print(m.id)
        return

    model = args.model or next(
        (m["id"] for m in enabled_models(registry) if m["provider"] == args.provider), None)
    if not model:
        sys.exit(f"No enabled {args.provider} model in models.yaml")

    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": args.question}]
    start = time.perf_counter()
    try:
        r = client.chat.completions.create(
            model=model, messages=messages, temperature=args.temperature, max_tokens=1024)
    except RateLimitError:
        sys.exit("Rate limited (HTTP 429): free-tier limit reached. Wait or try the other provider.")
    except APIConnectionError as e:
        sys.exit(f"Could not reach {args.provider}: {e}")
    except APIStatusError as e:
        sys.exit(f"{args.provider} returned HTTP {e.status_code}: {e.body}")
    elapsed = time.perf_counter() - start

    print(f"\nProvider : {args.provider}\nModel    : {model}\nTemp     : {args.temperature}")
    print(f"Latency  : {elapsed:.2f} s")
    if r.usage:
        print(f"Tokens   : {r.usage.prompt_tokens} in, {r.usage.completion_tokens} out")
    print(f"\nAnswer:\n{r.choices[0].message.content or '(empty answer)'}\n")


if __name__ == "__main__":
    main()