"""Compatibility launcher for ZENO's authoritative voice front door.

The old root-level assistant created its own microphone listener, wake loop,
brain, and speech queue.  Running it beside the desktop application could
therefore compete for the microphone and bypass the managed ZENO runtime.
Keep the familiar command without keeping a second implementation.
"""

from reyes_agent.voice_cli import main


if __name__ == "__main__":
    main()
