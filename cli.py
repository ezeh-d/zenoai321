"""The conversation loop — talk to REYES in your terminal."""
from __future__ import annotations

from brain import Brain
from config import settings


def _approver(action: str) -> bool:
    """Ask the user before a destructive action. Auto-yes if confirmation disabled."""
    if not settings.require_confirmation:
        return True
    try:
        answer = input(f"\n⚠  REYES wants to: {action}\n   Allow? [y/N] ").strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")


def _on_tool(info: str) -> None:
    print(f"   ⚙  using: {info}")


def main() -> None:
    print(f"\n  {settings.assistant_name} online. Talk to me. (type 'exit' to quit)\n")
    brain = Brain(approver=_approver, on_tool=_on_tool)
    try:
        while True:
            try:
                user = input(f"{settings.user_name} › ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not user:
                continue
            if user.lower() in ("exit", "quit", "bye"):
                break
            reply = brain.chat(user)
            print(f"\n{settings.assistant_name} › {reply}\n")
    finally:
        brain.close()
        print(f"\n{settings.assistant_name} offline. See you, {settings.user_name}.")


if __name__ == "__main__":
    main()
