"""Short alias so `python -m reyes_agent.status` shows the beautiful dashboard."""

from __future__ import annotations

from reyes_agent.status_dashboard import main

if __name__ == "__main__":
    raise SystemExit(main())
