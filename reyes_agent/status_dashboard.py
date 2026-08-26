"""A beautiful ZENO status dashboard for the terminal (`python -m reyes_agent.status`).

Everything integrated this cycle -- the capability truth, hands & messaging,
gated provider adapters, the mic -- surfaced in one polished CMD view. It reads
the REAL registry (no fabrication): an area with no tools shows as not
connected, a quarantined tool shows red. Uses `rich` when present and falls back
to clean plain text otherwise, so it never fails just because a pretty printer
is missing.
"""

from __future__ import annotations

from typing import Any

# ZENO palette.
_OK = "bold green"
_WARN = "bold yellow"
_BAD = "bold red"
_DIM = "grey62"
_ACCENT = "bold cyan"


def _mic_line() -> tuple[str, str]:
    """(device name, style) for the default input -- best-effort, no capture."""
    try:
        import sounddevice as sd

        info = sd.query_devices(kind="input")
        name = str(info.get("name", "unknown"))
        return name, _OK
    except Exception:  # noqa: BLE001
        return "no input device detected", _WARN


def _gather() -> dict[str, Any]:
    from reyes_agent import capability_snapshot as cs

    data: dict[str, Any] = {"status": {}, "hands": {}}
    try:
        data["status"] = cs.system_status()
    except Exception as exc:  # noqa: BLE001
        data["status_error"] = str(exc)
    try:
        data["hands"] = cs.hands_and_comms()
    except Exception:  # noqa: BLE001
        data["hands"] = {}
    data["mic"] = _mic_line()
    return data


def _status_style(value: str) -> str:
    v = str(value or "").upper()
    if v in {"READY", "AVAILABLE", "HEALTHY", "ONLINE", "OK", "CONNECTED"}:
        return _OK
    if v in {"PARTIAL", "DEGRADED", "AUTH_REQUIRED", "DEVICE_OFFLINE", "REQUIRES_SETUP",
             "TESTING", "DEVICE_REQUIRED"}:
        return _WARN
    return _BAD


# ---- rich renderer ---------------------------------------------------------
def _render_rich(data: dict[str, Any]) -> None:
    import sys

    from rich.box import ROUNDED
    from rich.console import Console, Group
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    # The Windows legacy console is cp1252 and cannot encode box-drawing or the
    # ⬢/● glyphs (UnicodeEncodeError). Switch stdout to UTF-8 and make rich emit
    # ANSI (modern Windows terminals support it) instead of the Win32 cp1252 API.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    console = Console(legacy_windows=False)
    status = data.get("status", {})
    hands = data.get("hands", {})

    tools = status.get("tools", 0)
    connected = status.get("areas_connected", 0)
    total = status.get("areas_total", 0)
    header = Text.assemble(
        ("  ⬢  ", _ACCENT), ("ZENO", "bold white"), ("  ·  SYSTEM STATUS", _DIM))
    sub = Text.assemble(
        (f"{tools}", _ACCENT), (" tools registered   ", _DIM),
        (f"{connected}/{total}", _ACCENT), (" capability areas connected", _DIM))
    console.print(Panel(Group(header, sub), box=ROUNDED, border_style="cyan",
                        padding=(1, 2)))

    # Capability areas.
    areas = status.get("areas", [])
    if areas:
        t = Table(box=ROUNDED, border_style=_DIM, title="Capabilities",
                  title_style=_ACCENT, expand=True)
        t.add_column("Area", style="white")
        t.add_column("Tools", justify="right")
        t.add_column("Status", justify="center")
        for a in areas:
            conn = a.get("connected")
            t.add_row(a.get("label", a.get("area", "?")),
                      str(a.get("tools", 0)),
                      Text("● connected" if conn else "○ not connected",
                           style=_OK if conn else _BAD))
        console.print(t)

    # Hands & comms + mic, side by side style.
    if hands:
        h = Table(box=ROUNDED, border_style=_DIM, title="Hands & Communication",
                  title_style=_ACCENT, expand=True)
        h.add_column("Capability", style="white")
        h.add_column("State", justify="center")
        flat: dict[str, Any] = {}
        for group in ("hands", "communication"):
            for k, v in (hands.get(group) or {}).items():
                flat[k] = v
        for k, v in (hands.items() if not flat else flat.items()):
            if isinstance(v, dict):
                continue
            h.add_row(str(k).replace("_", " ").title(), Text(str(v), style=_status_style(str(v))))
        mic_name, mic_style = data.get("mic", ("?", _DIM))
        h.add_row("Microphone (default)", Text(mic_name, style=mic_style))
        console.print(h)

    # Gated provider adapters.
    adapters = status.get("adapters", [])
    if adapters:
        ad = Table(box=ROUNDED, border_style=_DIM,
                   title="Provider adapters (gated · off by default)",
                   title_style=_ACCENT, expand=True)
        ad.add_column("Adapter", style="white")
        ad.add_column("Category", style=_DIM)
        ad.add_column("Readiness", justify="center")
        for a in adapters:
            st = a.get("status") or a.get("readiness") or ("available" if a.get("available") else "requires setup")
            ad.add_row(str(a.get("name", "?")), str(a.get("category", "")),
                       Text(str(st).replace("_", " "), style=_status_style(str(st))))
        console.print(ad)

    # Health footer.
    quarantined = status.get("quarantined", [])
    proven = status.get("proven_active", [])
    foot = Text()
    foot.append("Proven-active: ", style=_DIM)
    foot.append(", ".join(proven) if proven else "none yet", style=_OK if proven else _DIM)
    foot.append("      Quarantined: ", style=_DIM)
    foot.append(", ".join(quarantined) if quarantined else "none",
                style=_BAD if quarantined else _OK)
    console.print(Panel(foot, box=ROUNDED, border_style=_DIM, padding=(0, 2)))


# ---- plain fallback --------------------------------------------------------
def _render_plain(data: dict[str, Any]) -> None:
    status = data.get("status", {})
    print("=" * 52)
    print(f"  ZENO — SYSTEM STATUS")
    print(f"  {status.get('tools', 0)} tools · "
          f"{status.get('areas_connected', 0)}/{status.get('areas_total', 0)} areas connected")
    print("=" * 52)
    for a in status.get("areas", []):
        mark = "[+]" if a.get("connected") else "[ ]"
        print(f"  {mark} {a.get('label',''):22} {a.get('tools',0):>3} tools")
    hands = data.get("hands", {})
    if hands:
        print("  --- hands & comms ---")
        for k, v in hands.items():
            if not isinstance(v, dict):
                print(f"  {k:22} {v}")
    mic, _ = data.get("mic", ("?", ""))
    print(f"  microphone (default)   {mic}")
    q = status.get("quarantined", [])
    print(f"  quarantined: {', '.join(q) if q else 'none'}")


def render() -> None:
    data = _gather()
    try:
        import rich  # noqa: F401

        _render_rich(data)
    except Exception:  # noqa: BLE001 -- never fail just because pretty printing did
        _render_plain(data)


def main() -> int:
    render()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
