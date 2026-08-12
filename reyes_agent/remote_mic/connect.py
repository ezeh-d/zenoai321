"""Turning a chosen route into something the phone can scan.

This is the join between two things that were already separate and correct:
`routes.py` knows WHERE the phone can reach ZENO, and `phone_security.py`
knows HOW it proves it is allowed to. Neither needed changing to support a
second network -- an address and a token are independent, which is the whole
reason both networks can share one pairing system.

    "QR tokens remain short-lived and single-use."

They are, and this does not weaken that: the token comes from
`create_pair()` exactly as the Wi-Fi path always did. A hotspot QR is not a
lesser credential, it is the same credential printed with a different host.

WHAT REGENERATING A QR DOES TO THE OTHER ONE
--------------------------------------------
`create_pair()` cancels any unconsumed pair, so asking for a hotspot QR does
invalidate an outstanding Wi-Fi QR. That is a property of the token, not of
the route, and it is the safe direction: at most one pairing code is live at
a time. Both remain REGENERATABLE on demand, which is what the owner asked
for -- neither configuration is destroyed, and either can be reissued in a
second.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from reyes_agent.remote_mic import pairing, routes


def offer(mode: str = "", *, with_qr: bool = True) -> dict[str, Any]:
    """A scannable pairing offer for the requested network.

    `mode` is AUTO, LAN_WIFI or LAPTOP_HOTSPOT. An explicit mode that is not
    available comes back as a refusal naming what IS available, rather than
    quietly returning the other network -- being handed a Wi-Fi QR after
    asking for the hotspot is how an owner ends up scanning a code that
    cannot work from where they are standing.
    """
    from reyes_agent import config
    from reyes_agent.phone_security import get_phone_security

    wanted = (mode or "").strip().upper() or getattr(
        config, "REMOTE_MIC_NETWORK_MODE", routes.AUTO)
    selector = routes.selector()
    route = selector.choose(wanted)

    if route is None:
        available = selector.routes()
        if not available:
            return {"ok": False, "mode": wanted, "reason": (
                "No usable local network right now. Connect this laptop to "
                "Wi-Fi, or switch on Mobile Hotspot in Windows settings.")}
        names = ", ".join(sorted({r.label for r in available}))
        return {"ok": False, "mode": wanted, "reason": (
            f"{'The laptop hotspot' if wanted == routes.HOTSPOT else 'The Wi-Fi network'}"
            f" is not up, so I cannot make a code for it. Available now: {names}."),
            "routes": [r.as_dict() for r in available]}

    if route.health != routes.READY:
        return {"ok": False, "mode": wanted, "route": route.as_dict(), "reason": (
            f"{route.label} has an address ({route.ipv4}) but nothing is "
            f"listening on {routes.PORT}. Start the phone mic listener first.")}

    pair = get_phone_security().create_pair()
    url = route.url_with(pair["token"])
    result = {
        "ok": True,
        "mode": route.mode,
        "label": route.label,
        "url": url,
        "origin": route.origin,
        "ipv4": route.ipv4,
        "adapter": route.adapter_name,
        "port": routes.PORT,
        "manual_code": pair["manual_code"],
        "expires_at": pair["expires_at"],
        "route": route.as_dict(),
        "alternatives": [r.as_dict() for r in selector.routes() if r.ipv4 != route.ipv4],
        "chrome_flag": pairing.CHROME_FLAG,
        "steps": _steps(route),
    }
    if with_qr:
        result["qr_png"] = pairing._qr(url)
    return result


def standing(*, with_qr: bool = True) -> dict[str, Any]:
    """ONE permanent QR that works on Wi-Fi and on the hotspot.

    HOW ONE CODE COVERS TWO NETWORKS
    --------------------------------
    A QR holds one URL, and 192.168.1.117 is unreachable from the hotspot, so
    no IP address can cover both. A NAME can. Windows already publishes this
    machine over mDNS, and its responder answers PER INTERFACE -- measured
    here, a query arriving on the hotspot is answered 192.168.137.1 and a
    query arriving over Wi-Fi is answered 192.168.1.117. The phone therefore
    resolves the same name to whichever address it can actually reach.

    That also collapses the Chrome secure-origin flag from two entries to
    one, because http://<name>:8768 is a single origin on both networks.

    WHY IT NEVER EXPIRES
    --------------------
    It carries the STANDING key rather than a one-time token. See
    `PhoneSecurity.pair_with_mic_key`: it is still audio-only, still refused
    from outside this machine's own networks, and still rotatable in one
    call. Long-lived, never wider.
    """
    from reyes_agent.phone_security import get_phone_security

    host = mdns_host()
    selector = routes.selector()
    ready = [r for r in selector.routes() if r.health == routes.READY]
    if not host:
        return {"ok": False, "reason": (
            "I could not determine this computer's local network name, so I "
            "cannot make a single code for both networks.")}
    if not ready:
        return {"ok": False, "reason": (
            "No network is serving the phone mic yet. Start the listener, or "
            "connect to Wi-Fi or switch on Mobile Hotspot.")}

    origin = f"http://{host}:{routes.PORT}"
    url = f"{origin}/mic?k={get_phone_security().mic_key()}"
    result = {
        "ok": True,
        "kind": "STANDING",
        "url": url,
        "origin": origin,
        "host": host,
        "port": routes.PORT,
        "expires": None,
        "expires_note": "This code does not expire and can be scanned again.",
        "covers": [r.as_dict() for r in ready],
        "chrome_flag": pairing.CHROME_FLAG,
        "steps": [
            "On the phone open Chrome and go to chrome://flags",
            'Search "Insecure origins treated as secure"',
            f"Add {origin}, set it to Enabled, then relaunch Chrome",
            "Scan the code on either Wi-Fi or the laptop hotspot",
            "Allow the microphone when Chrome asks",
        ],
        "fallback": [f"http://{r.ipv4}:{routes.PORT}/mic" for r in ready],
        "fallback_note": ("If the phone cannot resolve the name, use the "
                          "matching address for the network it is on -- the "
                          "same key works at any of them."),
    }
    if with_qr:
        result["qr_png"] = pairing._qr(url)
    return result


def standing_by_address(*, with_qr: bool = True) -> dict[str, Any]:
    """The standing key printed for each network's literal IP address.

    The mDNS QR is the elegant one -- a single code for both networks -- but
    it depends on the phone resolving a `.local` name, and a name can resolve
    to something unreachable. Measured here: this machine's name answers with
    IPv6 first and a Tailscale address before either LAN address, and the
    listener binds IPv4 only, so several of those answers are dead ends.

    A literal address has none of those failure modes. It is the code to
    reach for when it simply has to work.

    Same standing key in every code -- the key authenticates the phone, not
    the route it arrived by, so all of these stay valid together.
    """
    from reyes_agent.phone_security import get_phone_security

    key = get_phone_security().mic_key()
    offers = []
    for route in routes.selector().routes():
        if route.health != routes.READY:
            continue
        url = f"{route.origin}/mic?k={key}"
        entry = {"mode": route.mode, "label": route.label, "ipv4": route.ipv4,
                 "origin": route.origin, "url": url, "steps": _steps(route)}
        if with_qr:
            entry["qr_png"] = pairing._qr(url)
        offers.append(entry)

    if not offers:
        return {"ok": False, "reason": (
            "No network is serving the phone mic. Start the listener, or "
            "connect to Wi-Fi or switch on Mobile Hotspot.")}
    return {"ok": True, "offers": offers, "expires": None,
            "chrome_flag": pairing.CHROME_FLAG,
            "note": ("One standing key, printed per network. Each address is "
                     "literal, so nothing depends on name resolution.")}


def save_by_address(directory: str | Path = "") -> dict[str, Any]:
    """Write one QR per available network, keyed to its literal address."""
    result = standing_by_address()
    if not result.get("ok"):
        return result
    folder = Path(directory) if directory else (Path.home() / "Desktop")
    folder.mkdir(parents=True, exist_ok=True)
    for entry in result["offers"]:
        name = "wifi" if entry["mode"] == routes.LAN_WIFI else "hotspot"
        target = folder / f"zeno_mic_{name}.png"
        target.write_bytes(base64.b64decode(entry.pop("qr_png").split(",")[-1]))
        entry["path"] = str(target)
    return result


def mdns_host() -> str:
    """This machine's `.local` name, which resolves on every local network."""
    import socket as _socket

    try:
        name = _socket.gethostname().split(".")[0].strip()
    except Exception:  # noqa: BLE001
        return ""
    return f"{name}.local" if name else ""


def save_standing(destination: str | Path = "") -> dict[str, Any]:
    """Write the one permanent QR to a file."""
    result = standing()
    if not result.get("ok"):
        return result
    target = Path(destination) if destination else (
        Path.home() / "Desktop" / "zeno_mic.png")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(base64.b64decode(result.pop("qr_png").split(",")[-1]))
    result["path"] = str(target)
    return result


def offer_both(*, with_qr: bool = True) -> dict[str, Any]:
    """One pairing code, printed for every available network.

    A token is not bound to an address -- it proves the owner is holding this
    laptop's screen, not that the phone is on a particular subnet. So both
    QR codes can carry the SAME token and both stay valid until one of them
    is scanned.

    That is what makes "keep both" real rather than a menu. The owner does
    not have to decide which network they are on before generating a code;
    they scan whichever one their phone can see, and the other dies with it
    because the token is still single-use.
    """
    from reyes_agent.phone_security import get_phone_security

    selector = routes.selector()
    ready = [r for r in selector.routes() if r.health == routes.READY]
    if not ready:
        return {"ok": False, "reason": (
            "No network is serving the phone mic yet. Start the listener, or "
            "connect this laptop to Wi-Fi or switch on Mobile Hotspot.")}

    pair = get_phone_security().create_pair()
    offers = []
    for route in ready:
        entry = {"mode": route.mode, "label": route.label, "ipv4": route.ipv4,
                 "adapter": route.adapter_name, "origin": route.origin,
                 "url": route.url_with(pair["token"]), "steps": _steps(route)}
        if with_qr:
            entry["qr_png"] = pairing._qr(entry["url"])
        offers.append(entry)

    return {"ok": True, "offers": offers, "manual_code": pair["manual_code"],
            "expires_at": pair["expires_at"], "port": routes.PORT,
            "chrome_flag": pairing.CHROME_FLAG,
            "shared_token": ("Both codes carry the same one-time token. Scan "
                             "whichever network your phone can see -- the "
                             "other stops working the moment one is used.")}


def save_both(directory: str | Path = "") -> dict[str, Any]:
    """Write a QR per available network. Both valid until one is scanned."""
    result = offer_both()
    if not result.get("ok"):
        return result
    folder = Path(directory) if directory else (Path.home() / "Desktop")
    folder.mkdir(parents=True, exist_ok=True)
    for entry in result["offers"]:
        target = folder / f"zeno_mic_{entry['mode'].lower()}.png"
        target.write_bytes(base64.b64decode(entry.pop("qr_png").split(",")[-1]))
        entry["path"] = str(target)
    return result


def _steps(route: routes.RemoteMicRoute) -> list[str]:
    """What the owner has to do, in the order they have to do it."""
    common = [
        "On the phone open Chrome and go to chrome://flags",
        'Search "Insecure origins treated as secure"',
        f"Add {route.origin}, set it to Enabled, then relaunch Chrome",
        "Scan the QR code and tap Pair and continue",
        "Allow the microphone when Chrome asks",
    ]
    if route.mode == routes.HOTSPOT:
        return ["On the phone, connect to this laptop's hotspot Wi-Fi", *common]
    return ["Make sure the phone is on the same Wi-Fi as this laptop", *common]


def save_qr(mode: str = "", destination: str | Path = "") -> dict[str, Any]:
    """Write the QR to a file. Returns the same offer plus `path`."""
    result = offer(mode)
    if not result.get("ok"):
        return result
    target = Path(destination) if destination else (
        Path.home() / "Desktop" / f"zeno_mic_qr_{result['mode'].lower()}.png")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(base64.b64decode(result["qr_png"].split(",")[-1]))
    result["path"] = str(target)
    return result


def say(result: dict[str, Any]) -> str:
    """One spoken sentence about a pairing offer."""
    if not result.get("ok"):
        return result.get("reason", "I could not make a pairing code.")
    where = ("my laptop hotspot" if result["mode"] == routes.HOTSPOT
             else "the Wi-Fi network")
    return (f"Here is the phone microphone code for {where}, at "
            f"{result['ipv4']}. It works once and expires in a few minutes.")


def status() -> dict[str, Any]:
    return {"state": "ONLINE", "networks": routes.status(),
            "token": "one-time, single-use, expires with PAIR_TTL_S",
            "scope": "remote_audio_send only, on either network"}
