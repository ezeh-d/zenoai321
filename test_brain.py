# test_brain.py

from __future__ import annotations

import sys

try:
    from brain import think
except ImportError as error:
    print(f"[IMPORT ERROR] Could not import brain.py: {error}")
    sys.exit(1)
except Exception as error:
    print(f"[STARTUP ERROR] brain.py failed to load: {error}")
    sys.exit(1)


def main() -> None:
    print("=" * 50)
    print("REYES BRAIN TEST MODE")
    print("=" * 50)
    print("Type a command and press Enter.")
    print("Type 'exit' or 'quit' to stop.")
    print("=" * 50)

    while True:
        try:
            command = input("\nYou: ").strip()

            if not command:
                continue

            if command.lower() in {
                "exit",
                "quit",
            }:
                print("REYES: Brain test stopped.")
                return

            response = think(command)

            if response is None:
                print("REYES: [No response returned]")
                continue

            print(f"REYES: {response}")

        except KeyboardInterrupt:
            print("\nREYES: Brain test stopped.")
            return

        except EOFError:
            print("\nREYES: Brain test stopped.")
            return

        except Exception as error:
            print(f"[BRAIN TEST ERROR] {error}")


if __name__ == "__main__":
    main()