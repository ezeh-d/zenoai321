"""Both networks, and neither one destroying the other."""

from __future__ import annotations

import pytest

from reyes_agent.remote_mic import failover, routes


def _rows(*entries):
    return [{"ip": ip, "alias": alias, "status": "Up", "description": desc}
            for ip, alias, desc in entries]


WIFI = ("192.168.1.117", "Wi-Fi", "Intel(R) Dual Band Wireless-AC 8260")
HOT = ("192.168.137.1", "Local Area Connection* 10",
       "Microsoft Wi-Fi Direct Virtual Adapter #2")


@pytest.fixture
def both(monkeypatch):
    monkeypatch.setattr(routes, "_adapters", lambda: _rows(WIFI, HOT))
    return routes.RemoteMicAddressSelector()


def test_finds_wifi_and_hotspot_together(both):
    found = {r.mode: r for r in both.routes(probe=False)}
    assert found[routes.LAN_WIFI].ipv4 == "192.168.1.117"
    assert found[routes.HOTSPOT].ipv4 == "192.168.137.1"


def test_both_use_the_same_port(both):
    assert {r.origin.rsplit(":", 1)[1] for r in both.routes(probe=False)} == {"8768"}


def test_auto_prefers_lan_but_hotspot_is_still_listed(both):
    chosen = both.choose(routes.AUTO, probe=False)
    assert chosen.mode == routes.LAN_WIFI
    # The point of the brief: choosing one must not remove the other.
    assert any(r.mode == routes.HOTSPOT for r in both.routes(probe=False))


def test_explicit_hotspot_is_honoured(both):
    assert both.choose(routes.HOTSPOT, probe=False).ipv4 == "192.168.137.1"


def test_auto_falls_back_to_hotspot_when_lan_is_gone(monkeypatch):
    monkeypatch.setattr(routes, "_adapters", lambda: _rows(HOT))
    assert routes.RemoteMicAddressSelector().choose(
        routes.AUTO, probe=False).mode == routes.HOTSPOT


def test_explicit_mode_is_never_silently_substituted(monkeypatch):
    """Asking for a network that is down gets nothing, not the other one.

    Handing back Wi-Fi when the owner asked for the hotspot produces a QR
    that cannot work from where they are standing.
    """
    monkeypatch.setattr(routes, "_adapters", lambda: _rows(WIFI))
    assert routes.RemoteMicAddressSelector().choose(
        routes.HOTSPOT, probe=False) is None


def test_hotspot_detected_by_description_off_the_ics_subnet(monkeypatch):
    """A hotspot moved off 192.168.137.x is still a hotspot."""
    monkeypatch.setattr(routes, "_adapters", lambda: _rows(
        ("192.168.44.1", "Local Area Connection* 3",
         "Microsoft Wi-Fi Direct Virtual Adapter")))
    assert routes.RemoteMicAddressSelector().routes(
        probe=False)[0].mode == routes.HOTSPOT


@pytest.mark.parametrize("ip,alias,desc", [
    ("169.254.85.30", "Ethernet", "Intel(R) Ethernet"),      # no DHCP: dead end
    ("127.0.0.1", "Loopback", "Software Loopback"),
    ("100.90.14.97", "Tailscale", "Tailscale Tunnel"),       # remote, not local
    ("172.17.0.1", "vEthernet (WSL)", "Hyper-V Virtual Ethernet"),
    ("8.8.8.8", "Wi-Fi", "public address on a local adapter"),
])
def test_unusable_addresses_are_never_offered(monkeypatch, ip, alias, desc):
    monkeypatch.setattr(routes, "_adapters", lambda: _rows((ip, alias, desc)))
    assert routes.RemoteMicAddressSelector().routes(probe=False) == []


def test_peer_address_decides_which_network_is_reported(both):
    """The answer comes from the socket, not from whichever QR was scanned."""
    assert both.route_for_peer("192.168.137.42").mode == routes.HOTSPOT
    assert both.route_for_peer("192.168.1.55").mode == routes.LAN_WIFI
    assert both.route_for_peer("10.0.0.9") is None


def test_offer_carries_a_token_for_either_network(monkeypatch):
    monkeypatch.setattr(routes, "_adapters", lambda: _rows(WIFI, HOT))
    monkeypatch.setattr(routes.RemoteMicAddressSelector, "routes",
                        lambda self, probe=True: [
                            routes.RemoteMicRoute(
                                mode=mode, ipv4=ip, adapter_name=alias,
                                origin=f"http://{ip}:8768",
                                mic_url=f"http://{ip}:8768/mic",
                                available=True, health=routes.READY,
                                priority=1 if mode == routes.LAN_WIFI else 2)
                            for mode, (ip, alias, _) in
                            ((routes.LAN_WIFI, WIFI), (routes.HOTSPOT, HOT))])

    from reyes_agent.remote_mic import connect

    for mode, host in ((routes.LAN_WIFI, "192.168.1.117"),
                       (routes.HOTSPOT, "192.168.137.1")):
        result = connect.offer(mode, with_qr=False)
        assert result["ok"], result
        assert result["url"].startswith(f"http://{host}:8768/mic?token=")
        assert len(result["url"].split("token=")[1]) >= 32


class _Clock:
    """A movable clock. Capture the real time BEFORE patching -- a lambda that
    calls time.time() after patching calls itself."""

    def __init__(self, monkeypatch):
        self.now = failover.time.time()
        monkeypatch.setattr(failover.time, "time", lambda: self.now)

    def advance(self, seconds):
        self.now += seconds


class TestFailover:
    def test_a_blink_is_not_announced(self, monkeypatch):
        watcher = failover.RouteWatcher()
        monkeypatch.setattr(routes, "_adapters", lambda: _rows(WIFI, HOT))
        watcher.inspect()
        monkeypatch.setattr(routes, "_adapters", lambda: _rows(HOT))
        assert watcher.inspect() == []      # inside the confirmation window

    def test_a_confirmed_loss_names_the_alternative(self, monkeypatch):
        watcher = failover.RouteWatcher()
        monkeypatch.setattr(routes, "_adapters", lambda: _rows(WIFI, HOT))
        watcher.inspect()
        monkeypatch.setattr(routes, "_adapters", lambda: _rows(HOT))
        clock = _Clock(monkeypatch)
        watcher.inspect()          # first sighting of the loss starts the timer
        clock.advance(60)
        changes = watcher.inspect()
        assert len(changes) == 1
        assert changes[0].lost == routes.LAN_WIFI
        assert changes[0].alternative == routes.HOTSPOT
        assert "hotspot is available" in changes[0].say()

    def test_loss_is_announced_once_not_every_pass(self, monkeypatch):
        watcher = failover.RouteWatcher()
        monkeypatch.setattr(routes, "_adapters", lambda: _rows(WIFI, HOT))
        watcher.inspect()
        monkeypatch.setattr(routes, "_adapters", lambda: _rows(HOT))
        clock = _Clock(monkeypatch)
        watcher.inspect()
        clock.advance(60)
        assert len(watcher.inspect()) == 1
        assert watcher.inspect() == []

    def test_it_never_claims_a_live_session_moved(self, monkeypatch):
        """No wording may suggest the WebRTC session survived the change."""
        change = failover.Change(lost=routes.LAN_WIFI, alternative=routes.HOTSPOT,
                                 was_carrying_audio=True)
        spoken = change.say().lower()
        assert "dropped" in spoken
        assert "reconnect" in spoken
        for lie in ("switched", "moved", "transferred", "seamless", "kept"):
            assert lie not in spoken


class TestLocalAddressAcrossIPVersions:
    """The QR carries an mDNS name, and Windows answers it with IPv6 FIRST.

    An IPv4-only check refuses every one of those answers -- a phone being
    told "connect to my Wi-Fi first" while it is already on it. Caught the
    night before it mattered.
    """

    @pytest.mark.parametrize("address,local,why", [
        ("fe80::9c42:c4e5:fc47:ee", True, "link-local: same physical link by definition"),
        ("fd12:3456::1", True, "unique-local: private by design"),
        ("::ffff:192.168.1.55", True, "IPv4-mapped, on our LAN"),
        ("::ffff:8.8.8.8", False, "IPv4-mapped, public"),
        ("2a00:1450:4009:81f::200e", False, "global IPv6 on somebody else's network"),
        ("192.168.1.55", True, "plain LAN IPv4"),
        ("8.8.8.8", False, "public IPv4"),
        ("127.0.0.1", True, "loopback"),
        ("not-an-address", False, "garbage"),
    ])
    def test_classification(self, address, local, why):
        assert routes.is_local_address(address) is local, why

    def test_a_zone_index_does_not_break_parsing(self):
        """Windows hands back fe80::1%12; the zone is not part of the address."""
        assert routes.is_local_address("fe80::9c42:c4e5:fc47:ee%18") is True

    def test_a_global_ipv6_is_allowed_only_inside_our_own_prefix(self, monkeypatch):
        """Global IPv6 is internet-routable, so it is never blanket-allowed."""
        monkeypatch.setattr(routes, "own_ipv6",
                            lambda: ["2605:59c1:19ef:5310:1f4:860:e8bd:cbb4"])
        assert routes.is_local_address("2605:59c1:19ef:5310:aaaa:bbbb:cccc:dddd")
        assert not routes.is_local_address("2605:59c1:9999:5310:aaaa:bbbb:cccc:dddd")
