"""Tier 1+2: the text conversation loop, now with tools.

Read input, run it through the shared agent core (which may call tools
along the way), stream the reply, repeat. Still no audio, no memory across
restarts -- this stays the debug path once later tiers land.
"""

from __future__ import annotations

import sys

from reyes_agent import config, warmup
from reyes_agent.agent import run_agent
from reyes_agent.provider import ProviderError

EXIT_WORDS = {"exit", "quit", "bye", ":q"}


def main() -> None:
    # Windows consoles often default to a legacy codepage; force UTF-8 so
    # punctuation and non-ASCII text from the model don't get mangled.
    sys.stdout.reconfigure(encoding="utf-8")
    warmup.start_background_keepalive()

    history: list[dict] = []
    print(f"{config.ASSISTANT_NAME} -- online. Type 'exit' to quit.\n")

    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue
        if user_input.lower() in EXIT_WORDS:
            break

        turn_start = len(history)
        history.append({"role": "user", "content": user_input})

        print(f"{config.ASSISTANT_NAME}> ", end="", flush=True)

        def on_text(chunk: str) -> None:
            print(chunk, end="", flush=True)

        def on_tool_call(name: str, tool_input: dict, _id: str) -> None:
            print(f"\n  [using {name}({tool_input})]")
            print(f"{config.ASSISTANT_NAME}> ", end="", flush=True)

        try:
            run_agent(history, on_text=on_text, on_tool_call=on_tool_call)
            print()
        except ProviderError as exc:
            print(f"\n[{config.ASSISTANT_NAME} couldn't respond: {exc}]")
            del history[turn_start:]  # revert the whole turn, not just the last entry
            continue


if __name__ == "__main__":
    main()
