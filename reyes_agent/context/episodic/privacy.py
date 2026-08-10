from __future__ import annotations

import os

_DEFAULT = ("1password", "bitwarden", "keepass", "bank", "wallet", "incognito", "inprivate", "authentication", "sign in")


def exclusions() -> tuple[str, ...]:
    custom = tuple(item.strip().casefold() for item in os.environ.get("ZENO_EPISODIC_EXCLUSIONS", "").split(",") if item.strip())
    return tuple(dict.fromkeys((*_DEFAULT, *custom)))


def allowed(title: str, application: str = "") -> bool:
    haystack = f"{title} {application}".casefold()
    return not any(marker in haystack for marker in exclusions())
