"""Every local address the phone could reach ZENO on -- Wi-Fi AND hotspot.

WHY THIS EXISTS AT ALL
----------------------
`pairing.lan_ip()` finds an address by opening a UDP socket toward 8.8.8.8 and
reading back which local address the routing table picked. That is a good
trick and it answers exactly one question: "which interface reaches the
internet". The laptop's own hotspot is not that interface and never will be,
so the old code could not have found it no matter what the owner asked for.

Hence real adapter enumeration. This is the difference between "the address I
use for the internet" and "every address a phone in this room could dial".

WHY BOTH ROUTES STAY ALIVE
--------------------------
    "Do not destroy one configuration when the other is enabled."

Nothing here mutates network state. It does not create, start, stop or
reconfigure a hotspot; it reads. Turning one route on cannot turn the other
off, because there is no switch -- there is a list, and both entries are in
it whenever Windows says both adapters are up.

The server already binds 0.0.0.0, so a single listener on one port is
reachable through every approved interface at once. There is no second
server, no second port, and no second audio pipeline: both routes are just
different doors into the same one.

WHAT IS DELIBERATELY EXCLUDED
-----------------------------
Link-local 169.254.x addresses (Windows assigns these when an adapter has no
real connectivity -- a route to one is a route to nothing), loopback, and the
Tailscale tunnel. Tailscale is a genuine transport but it is a REMOTE one and
`pairing.py` already owns it; mixing it in here would let "use my hotspot"
silently resolve to a route over the internet.
"""

from __future__ import annotations

import ipaddress
import socket
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

# The port is fixed and shared. The owner was explicit that it must not move,
# and there is no reason for it to: one listener on 0.0.0.0 already answers on
# every interface.
PORT = 8768

LAN_WIFI = "LAN_WIFI"
HOTSPOT = "LAPTOP_HOTSPOT"
AUTO = "AUTO"
MODES = (AUTO, LAN_WIFI, HOTSPOT)

# Health, worst to best.
DOWN = "DOWN"                    # no such route right now
ADAPTER_READY = "ADAPTER_READY"  # the address exists, nothing is listening
READY = "READY"                  # the address exists and the server answered

# Windows Internet Connection Sharing hands the hotspot adapter this subnet.
# It is the single strongest signal that an address belongs to the laptop's
# own hotspot rather than to a router.
_ICS_SUBNET = ipaddress.ip_network("192.168.137.0/24")

# Adapter aliases/descriptions Windows gives the Mobile Hotspot. Checked in
# addition to the subnet because a machine can be configured off the ICS
# default, and checked BEFORE falling back to "it looks like a LAN".
_HOTSPOT_HINTS = ("wi-fi direct", "wifi direct", "local area connection*",
                  "mobile hotspot", "hosted network", "soft ap", "softap")

# Never offer these as a phone route.
_SKIP_HINTS = ("loopback", "tailscale", "vethernet", "vmware", "virtualbox",
               "hyper-v", "docker", "bluetooth", "tap-windows", "wireguard",
               "zerotier", "tun")

_PROBE_TIMEOUT_S = 0.35

# Addresses are read from psutil on every call -- it is an in-process syscall
# and costs microseconds, so route changes are noticed immediately. Adapter
# DESCRIPTIONS come from PowerShell, which costs seconds, and are cached far
# longer: a description is a property of the hardware and does not change
# when a network comes or goes.
_DESCRIPTION_TTL_S = 120.0
_cache: dict[str, Any] = {"at": 0.0, "descriptions": {}}


@dataclass
class RemoteMicRoute:
    """One usable way for the phone to reach ZENO."""

    mode: str = ""
    adapter_name: str = ""
    ipv4: str = ""
    origin: str = ""
    mic_url: str = ""
    available: bool = False
    priority: int = 99
    latency_ms: float = 0.0
    health: str = DOWN
    detail: str = ""

    @property
    def label(self) -> str:
        return "Laptop Hotspot" if self.mode == HOTSPOT else "Same Wi-Fi"

    def url_with(self, token: str) -> str:
        """The mic URL carrying a one-time pairing token."""
        return f"{self.mic_url}?token={token}" if token else self.mic_url

    def as_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "label": self.label,
                "adapter_name": self.adapter_name, "ipv4": self.ipv4,
                "origin": self.origin, "mic_url": self.mic_url,
                "available": self.available, "priority": self.priority,
                "latency_ms": round(self.latency_ms, 1), "health": self.health,
                "detail": self.detail}


def _descriptions() -> dict[str, str]:
    """{adapter alias: hardware description}, cached hard.

    Only PowerShell knows that "Local Area Connection* 10" is a Wi-Fi Direct
    Virtual Adapter, and that is the signal that identifies a hotspot running
    off the ICS default subnet. But it costs seconds, so it is fetched once
    and reused -- a description does not change when a network drops.

    ONE query for all adapters. The first version of this called
    Get-NetAdapter per address and took seven seconds.
    """
    if _cache["descriptions"] and time.time() - _cache["at"] < _DESCRIPTION_TTL_S:
        return _cache["descriptions"]

    script = ("Get-NetAdapter -ErrorAction SilentlyContinue | "
              "ForEach-Object { '{0}|{1}' -f $_.Name, $_.InterfaceDescription }")
    found: dict[str, str] = {}
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=12,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for line in (done.stdout or "").splitlines():
            alias, _, description = line.strip().partition("|")
            if alias:
                found[alias.strip()] = description.strip()
    except Exception:  # noqa: BLE001
        found = {}

    if found:
        _cache.update({"at": time.time(), "descriptions": found})
    return found or _cache["descriptions"]


def _adapters() -> list[dict[str, str]]:
    """Live IPv4 addresses, enriched with cached descriptions.

    psutil is the source of truth for WHAT IS UP RIGHT NOW because it is an
    in-process call -- a hotspot that just started is visible on the next
    call, with no subprocess in the path. That matters for fallback: a route
    that disappeared should be noticed at once, not after a cache expires.
    """
    try:
        import psutil

        stats = psutil.net_if_stats()
    except Exception:  # noqa: BLE001
        return []

    described = _descriptions()
    rows: list[dict[str, str]] = []
    for name, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if getattr(addr, "family", None) == socket.AF_INET and addr.address:
                rows.append({"ip": addr.address, "alias": name,
                             "status": "Up" if getattr(stats.get(name), "isup", False)
                                       else "Down",
                             "description": described.get(name, "")})
    return rows


def local_subnets() -> list[str]:
    """This machine's own private IPv4 addresses. No subprocess, ever.

    `_adapters()` enriches addresses with adapter DESCRIPTIONS, which costs a
    PowerShell call. That is fine for building a UI; it is wrong on a request
    path, where it once turned a pairing check into a multi-second hang.
    Subnet membership only needs addresses, and psutil has those in-process.
    """
    try:
        import psutil

        stats = psutil.net_if_stats()
    except Exception:  # noqa: BLE001
        return []

    found: list[str] = []
    for name, addrs in psutil.net_if_addrs().items():
        if not getattr(stats.get(name), "isup", False):
            continue
        if any(hint in name.lower() for hint in _SKIP_HINTS):
            continue
        for addr in addrs:
            if getattr(addr, "family", None) != socket.AF_INET or not addr.address:
                continue
            try:
                parsed = ipaddress.ip_address(addr.address)
            except ValueError:
                continue
            if parsed.is_private and not parsed.is_loopback and not parsed.is_link_local:
                found.append(addr.address)
    return found


def own_ipv6() -> list[str]:
    """This machine's own IPv6 addresses. Needed to judge a global one."""
    try:
        import psutil

        stats = psutil.net_if_stats()
    except Exception:  # noqa: BLE001
        return []

    found: list[str] = []
    for name, addrs in psutil.net_if_addrs().items():
        if not getattr(stats.get(name), "isup", False):
            continue
        if any(hint in name.lower() for hint in _SKIP_HINTS):
            continue
        for addr in addrs:
            if getattr(addr, "family", None) != getattr(socket, "AF_INET6", -1):
                continue
            raw = str(addr.address or "").split("%")[0]
            if raw:
                found.append(raw)
    return found


def is_local_address(peer_ip: str) -> bool:
    """Is this address on one of THIS machine's own local networks.

    IPv6 IS NOT OPTIONAL HERE. The QR code carries an mDNS name, and Windows
    answers that name with IPv6 FIRST -- link-local fe80:: and a global
    2605:... before any IPv4. An IPv4-only check refuses every one of them,
    which is a phone being told "connect to my Wi-Fi first" while it is
    already on it.

    The four cases, and why each is decided the way it is:

      * IPv4-mapped (::ffff:192.168.1.5) -- unwrap and judge as IPv4. Dual
        stack sockets deliver IPv4 peers in this form.
      * Link-local (fe80::/10) -- on the same physical link BY DEFINITION.
        It cannot be routed off the network, so reaching us from one means
        being on it.
      * Unique local (fc00::/7) -- private by design, same as 192.168/16.
      * Global (2605:...) -- routable from the internet, so NEVER blanket
        allowed. Permitted only when it shares a /64 with one of this
        machine's own global addresses, which is what "same subnet" means in
        IPv6. A stranger's address will not match that prefix.
    """
    raw = (peer_ip or "").strip().split("%")[0]      # drop any zone index
    try:
        peer = ipaddress.ip_address(raw)
    except ValueError:
        return False
    if peer.is_loopback:
        return True

    if peer.version == 6:
        mapped = getattr(peer, "ipv4_mapped", None)
        if mapped is not None:
            return is_local_address(str(mapped))
        if peer.is_link_local:
            return True
        if peer in ipaddress.ip_network("fc00::/7"):
            return True
        for mine in own_ipv6():
            try:
                candidate = ipaddress.ip_address(mine)
            except ValueError:
                continue
            if candidate.version != 6 or candidate.is_link_local:
                continue
            if peer in ipaddress.ip_network(f"{mine}/64", strict=False):
                return True
        return False

    for mine in local_subnets():
        try:
            if peer in ipaddress.ip_network(f"{mine}/24", strict=False):
                return True
        except ValueError:
            continue
    return False


def _classify(ip: str, alias: str, description: str) -> str:
    """LAN_WIFI, HOTSPOT, or "" for addresses no phone should be sent to."""
    text = f"{alias} {description}".lower()
    if any(hint in text for hint in _SKIP_HINTS):
        return ""
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return ""
    if address.is_loopback or address.is_link_local:
        # 169.254.x means Windows gave up finding a DHCP server. Handing that
        # to a phone produces a QR code that cannot possibly connect.
        return ""
    if not address.is_private:
        # A public address on a local adapter would expose the mic page to
        # more than this room. The owner drew that line himself.
        return ""
    if address in _ICS_SUBNET or any(hint in text for hint in _HOTSPOT_HINTS):
        return HOTSPOT
    return LAN_WIFI


def _probe(ip: str, port: int) -> tuple[bool, float]:
    """Is the server actually answering on this interface, and how fast."""
    started = time.perf_counter()
    probe = socket.socket()
    probe.settimeout(_PROBE_TIMEOUT_S)
    try:
        reachable = probe.connect_ex((ip, port)) == 0
    except Exception:  # noqa: BLE001
        reachable = False
    finally:
        probe.close()
    return reachable, (time.perf_counter() - started) * 1000.0


class RemoteMicAddressSelector:
    """Enumerates the real routes and picks between them."""

    def __init__(self, port: int = PORT) -> None:
        self.port = port

    def routes(self, *, probe: bool = True) -> list[RemoteMicRoute]:
        """Every route Windows currently offers, best first.

        Both modes always appear when their adapter is up. Neither is
        derived from the other and neither cancels the other.
        """
        found: list[RemoteMicRoute] = []
        seen: set[str] = set()

        for row in _adapters():
            ip, alias = row["ip"], row["alias"]
            if ip in seen:
                continue
            mode = _classify(ip, alias, row.get("description", ""))
            if not mode:
                continue
            status = (row.get("status") or "").lower()
            if status and status not in ("up", ""):
                continue
            seen.add(ip)

            origin = f"http://{ip}:{self.port}"
            route = RemoteMicRoute(
                mode=mode, adapter_name=alias, ipv4=ip, origin=origin,
                mic_url=f"{origin}/mic", available=True,
                # LAN first in AUTO: the phone is usually already on the
                # router's network, so choosing it costs the owner nothing.
                # The hotspot is the answer when that is not true.
                priority=1 if mode == LAN_WIFI else 2,
                health=ADAPTER_READY,
                detail=row.get("description", "") or alias)

            if probe:
                listening, latency = _probe(ip, self.port)
                route.latency_ms = latency
                route.health = READY if listening else ADAPTER_READY
                if not listening:
                    route.detail = (f"{route.detail} -- adapter is up but nothing "
                                    f"is listening on {self.port} yet")
            found.append(route)

        found.sort(key=lambda r: (r.health != READY, r.priority, r.latency_ms))
        return found

    def choose(self, mode: str = "", *, probe: bool = True) -> RemoteMicRoute | None:
        """The route to use for a given request.

        AUTO prefers LAN when it is genuinely ready and falls back to the
        hotspot. An EXPLICIT mode is never silently substituted -- if the
        owner asks for the hotspot and the hotspot is off, that is an answer
        ("it is off"), not an invitation to hand back Wi-Fi.
        """
        wanted = (mode or "").strip().upper() or AUTO
        if wanted not in MODES:
            wanted = AUTO
        available = self.routes(probe=probe)
        if not available:
            return None
        if wanted == AUTO:
            ready = [r for r in available if r.health == READY]
            return (ready or available)[0]
        exact = [r for r in available if r.mode == wanted]
        if not exact:
            return None
        exact.sort(key=lambda r: (r.health != READY, r.latency_ms))
        return exact[0]

    def by_ip(self, ip: str) -> RemoteMicRoute | None:
        """Which route an address belongs to -- used to report, from real
        state, how a connected phone actually got here."""
        for route in self.routes(probe=False):
            if route.ipv4 == ip:
                return route
        return None

    def route_for_peer(self, peer_ip: str) -> RemoteMicRoute | None:
        """Which of our routes a CONNECTED PHONE came in through.

        Matched by subnet: a phone on 192.168.137.x arrived through the
        hotspot, a phone on 192.168.1.x through the router. This is how
        "which network is my phone using" gets answered from fact rather
        than from whichever mode was requested when the QR was made.
        """
        try:
            peer = ipaddress.ip_address(peer_ip)
        except ValueError:
            return None
        for route in self.routes(probe=False):
            try:
                network = ipaddress.ip_network(f"{route.ipv4}/24", strict=False)
            except ValueError:
                continue
            if peer in network:
                return route
        return None


_selector = RemoteMicAddressSelector()


def selector() -> RemoteMicAddressSelector:
    return _selector


def status() -> dict[str, Any]:
    """What the owner sees, and what ZENO answers network questions from."""
    from reyes_agent import config

    configured = getattr(config, "REMOTE_MIC_NETWORK_MODE", AUTO)
    found = _selector.routes()
    chosen = _selector.choose(configured)
    by_mode = {mode: [r.as_dict() for r in found if r.mode == mode]
               for mode in (LAN_WIFI, HOTSPOT)}
    return {
        "state": "ONLINE" if any(r.health == READY for r in found) else (
            "ADAPTERS_ONLY" if found else "NO_LOCAL_NETWORK"),
        "configured_mode": configured,
        "selected": chosen.as_dict() if chosen else None,
        "routes": [r.as_dict() for r in found],
        "lan_wifi": by_mode[LAN_WIFI],
        "hotspot": by_mode[HOTSPOT],
        "port": PORT,
        "both_supported": bool(by_mode[LAN_WIFI]) and bool(by_mode[HOTSPOT]),
        "note": ("One listener on 0.0.0.0:%d answers on every approved "
                 "interface, so Wi-Fi and hotspot are two doors into the same "
                 "audio pipeline -- not two pipelines." % PORT),
    }
