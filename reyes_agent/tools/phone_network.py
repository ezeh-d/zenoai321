"""Voice-facing tools for choosing which network carries the phone mic.

These exist so the owner can say "use the laptop hotspot" instead of editing
an environment variable. Every one of them reads real adapter state -- there
is no cached answer to "which network is my phone on", because the only
honest source is the socket the audio is arriving on.
"""

from __future__ import annotations

import json

from reyes_agent.tools import register


@register(name="phone_mic_networks",
          description=("Show every local network the phone can use for the "
                       "microphone -- normal Wi-Fi and laptop hotspot -- with "
                       "real addresses and readiness."),
          input_schema={"type": "object", "properties": {}})
def phone_mic_networks() -> str:
    from reyes_agent.remote_mic import routes

    state = routes.status()
    lines = ["ZENO REMOTE MIC", "", "Available connections:", ""]
    for index, route in enumerate(state["routes"], start=1):
        lines.append(f"[{index}] {route['label']}")
        lines.append(f"    {route['ipv4']}:{state['port']}")
        lines.append(f"    {route['health']}")
        lines.append("")
    if not state["routes"]:
        lines.append("None. Connect to Wi-Fi, or switch on Mobile Hotspot.")
        lines.append("")
    lines.append(f"Mode: {state['configured_mode']}  (AUTO / LAN_WIFI / LAPTOP_HOTSPOT)")
    return json.dumps({"display": "\n".join(lines), **state}, default=str)


@register(name="phone_mic_qr",
          description=("Generate a phone microphone QR code for a chosen "
                       "network. mode is AUTO (best available), LAN_WIFI "
                       "(normal Wi-Fi) or LAPTOP_HOTSPOT."),
          input_schema={"type": "object", "properties": {
              "mode": {"type": "string",
                       "enum": ["AUTO", "LAN_WIFI", "LAPTOP_HOTSPOT"]},
              "save_to": {"type": "string",
                          "description": "Optional file path for the PNG."}}})
def phone_mic_qr(mode: str = "AUTO", save_to: str = "") -> str:
    from reyes_agent.remote_mic import connect

    result = connect.save_qr(mode, save_to) if save_to else connect.offer(mode)
    result.pop("qr_png", None)      # never inline a QR image into a transcript
    result["spoken"] = connect.say(result)
    return json.dumps(result, default=str)


@register(name="phone_mic_set_network",
          description=("Choose which local network ZENO prefers for the phone "
                       "microphone: AUTO, LAN_WIFI or LAPTOP_HOTSPOT. This "
                       "sets a preference only -- both networks keep working."),
          input_schema={"type": "object", "properties": {
              "mode": {"type": "string",
                       "enum": ["AUTO", "LAN_WIFI", "LAPTOP_HOTSPOT"]}},
              "required": ["mode"]})
def phone_mic_set_network(mode: str) -> str:
    from reyes_agent import config
    from reyes_agent.remote_mic import routes

    wanted = (mode or "").strip().upper()
    if wanted not in routes.MODES:
        return json.dumps({"ok": False, "reason": (
            f"'{mode}' is not a network mode. Use AUTO, LAN_WIFI or "
            "LAPTOP_HOTSPOT.")})

    # A PREFERENCE, not a switch. Nothing is torn down: the listener still
    # binds every approved interface, so the other network stays usable and
    # its QR stays regeneratable. The owner asked for exactly this.
    previous = getattr(config, "REMOTE_MIC_NETWORK_MODE", routes.AUTO)
    config.REMOTE_MIC_NETWORK_MODE = wanted
    chosen = routes.selector().choose(wanted)

    if chosen is None:
        # Say so rather than silently falling back -- being told "done" and
        # then handed the other network is worse than being told the truth.
        available = routes.selector().routes()
        config.REMOTE_MIC_NETWORK_MODE = previous
        return json.dumps({"ok": False, "mode": wanted, "reverted_to": previous,
                           "reason": ("That network is not up right now, so I "
                                      "have left the setting alone."),
                           "available": [r.as_dict() for r in available]})

    return json.dumps({
        "ok": True, "mode": wanted, "previous": previous,
        "selected": chosen.as_dict(),
        "spoken": (f"Phone microphone will use "
                   f"{'my laptop hotspot' if chosen.mode == routes.HOTSPOT else 'the normal Wi-Fi network'}"
                   f", at {chosen.ipv4}." if wanted != routes.AUTO else
                   f"I'll pick whichever phone connection is best. Right now "
                   f"that is {chosen.label.lower()}, at {chosen.ipv4}."),
        "both_still_available": True,
    }, default=str)


@register(name="phone_mic_current_network",
          description=("Report which network the phone microphone is actually "
                       "arriving on right now, read from the live connection."),
          input_schema={"type": "object", "properties": {}})
def phone_mic_current_network() -> str:
    from reyes_agent.remote_mic import failover, get_remote_mic_runtime, routes

    live = get_remote_mic_runtime().status()
    peer = str(live.get("peer_ip") or "")
    route = routes.selector().route_for_peer(peer) if peer else None

    if route is None:
        # No connection, or an address that matches no known route. Both are
        # "I don't know", and neither is worth a confident guess.
        spoken = ("No phone microphone is connected right now."
                  if not peer else
                  f"A phone is connected from {peer}, but that does not match "
                  "either of my local networks.")
    else:
        where = ("my laptop hotspot" if route.mode == routes.HOTSPOT
                 else "the normal Wi-Fi network")
        spoken = f"I'm receiving your phone microphone through {where}."

    return json.dumps({
        "connected": bool(peer), "peer_ip": peer,
        "mode": route.mode if route else "", "via": route.as_dict() if route else None,
        "audio_state": live.get("state", ""),
        "frames_received": live.get("received_frames", 0),
        "spoken": spoken,
        "watcher": failover.status(),
    }, default=str)
