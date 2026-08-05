# test_ollama.py

from __future__ import annotations

import sys

try:
    from ollama_ai import ask_ai
except ImportError as error:
    print(f"[IMPORT ERROR] Could not import ollama_ai.py: {error}")
    sys.exit(1)
except Exception as error:
    print(f"[STARTUP ERROR] ollama_ai.py failed to load: {error}")
    sys.exit(1)


def main() -> None:
    print("=" * 48)
    print("REYES OLLAMA TEST")
    print("=" * 48)
    print("Sending a request to the local Ollama model...")
    print()

    try:
        answer = ask_ai(
            "Who are you? Reply briefly and introduce yourself as REYES."
        )

        if not answer:
            print("[FAILED] Ollama returned an empty response.")
            sys.exit(1)

        print(f"REYES: {answer}")
        print()

        lower_answer = answer.lower()

        error_phrases = {
            "could not connect",
            "connection failed",
            "could not get a response",
            "ollama is not running",
            "model not found",
        }

        if any(phrase in lower_answer for phrase in error_phrases):
            print("[FAILED] The Ollama request was not successful.")
            sys.exit(1)

        print("[PASSED] ollama_ai.py is responding.")

        if "reyes" not in lower_answer:
            print(
                "[WARNING] The model did not introduce itself as REYES. "
                "Check SYSTEM_PROMPT in config.py or ollama_ai.py."
            )

    except KeyboardInterrupt:
        print("\nTest stopped.")
        sys.exit(1)

    except Exception as error:
        print(f"[TEST ERROR] {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()