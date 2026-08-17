from __future__ import annotations

import asyncio
from fractions import Fraction
from pathlib import Path
import time

from reyes_agent.audio.manager import AudioManager, get_audio_manager
from reyes_agent.phone_security import DEFAULT_SCOPES, REMOTE_AUDIO_SEND
from reyes_agent.remote_access.boundary import remote_path_allowed
from reyes_agent.remote_mic.quality import AudioQuality
from reyes_agent.remote_mic.runtime import RemoteMicRuntime, _WAKE, _wav
from reyes_agent.remote_mic.selector import MicrophoneSelector


def test_remote_audio_is_a_narrow_paired_capability() -> None:
    assert REMOTE_AUDIO_SEND in DEFAULT_SCOPES
    assert remote_path_allowed("/mic")
    assert remote_path_allowed("/api/phone/mic/offer")
    assert not remote_path_allowed("/api/phone/admin/mic/status")


def test_tailscale_serve_identity_is_treated_as_remote() -> None:
    from reyes_agent.remote_access.boundary import decision, is_forwarded_remote

    headers = {"tailscale-user-login": "owner@example.com",
               "host": "zeno.example-tail.ts.net"}
    assert is_forwarded_remote(headers)
    assert decision("/mic", headers, enabled=True)[0]
    allowed, status, _ = decision("/api/status", headers, enabled=True)
    assert not allowed and status == 403


def test_direct_lan_peer_is_confined_to_the_phone_surface() -> None:
    from reyes_agent.remote_access.boundary import decision, is_direct_remote

    assert is_direct_remote("192.168.1.50")
    assert not is_direct_remote("127.0.0.1")
    assert decision("/mic", {}, enabled=False, client_host="192.168.1.50",
                    local_enabled=True)[0]
    allowed, status, _ = decision(
        "/api/chat", {}, enabled=False, client_host="192.168.1.50",
        local_enabled=True)
    assert not allowed and status == 403
    allowed, status, _ = decision(
        "/mic", {}, enabled=False, client_host="192.168.1.50",
        local_enabled=False)
    assert not allowed and status == 503


def test_production_server_uses_one_process_for_desktop_and_phone_sockets() -> None:
    source = (Path(__file__).parents[1] / "reyes_agent" / "web.py").read_text("utf-8")
    main = source.split("def main() -> None:", 1)[1]
    assert 'bind("127.0.0.1", 8765)' in main
    assert 'bind("0.0.0.0", int(config.PHONE_COMPANION_PORT))' in main
    assert "server.run(sockets=sockets)" in main
    assert "subprocess.Popen" not in main, "the phone listener must not create a second ZENO"


def test_tailscale_https_origin_survives_the_loopback_proxy_hop(monkeypatch) -> None:
    from starlette.requests import Request
    from reyes_agent.web import _phone_origin

    monkeypatch.delenv("ZENO_PHONE_PUBLIC_HOST", raising=False)
    request = Request({
        "type": "http", "scheme": "http", "method": "POST", "path": "/api/phone/login/options",
        "headers": [(b"host", b"desktop.example-tail.ts.net"),
                    (b"tailscale-user-login", b"owner@example.com")],
        "client": ("127.0.0.1", 1234), "server": ("127.0.0.1", 8765),
    })
    assert _phone_origin(request) == (
        "https://desktop.example-tail.ts.net", "desktop.example-tail.ts.net")


def test_audio_manager_selects_exactly_one_source() -> None:
    manager = AudioManager(capacity=8)
    manager.unsubscribe("wake")
    seen: list[str] = []
    manager.subscribe("test", lambda frame: seen.append(frame.source))
    payload = (100).to_bytes(2, "little", signed=True) * 160
    manager.publish(payload, source="webview2-mini-orb")
    deadline = time.time() + 1
    while not seen and time.time() < deadline:
        time.sleep(0.01)
    manager.set_active_source("phone:one")
    manager.publish(payload, source="webview2-mini-orb")
    manager.publish(payload, source="phone:one")
    manager.publish(payload, source="phone:two")
    deadline = time.time() + 1
    while len(seen) < 2 and time.time() < deadline:
        time.sleep(0.01)
    manager.shutdown()
    assert seen == ["webview2-mini-orb", "phone:one"]


def test_selector_hysteresis_promotes_and_falls_back() -> None:
    selector = MicrophoneSelector()
    source = "phone:test"
    selected, changed = selector.observe(source, 90, now=1.0)
    assert selected is None and not changed
    selected, changed = selector.observe(source, 90, now=1.13)
    assert selected == source and changed
    assert selector.observe(source, 10, now=2.0) == (source, False)
    assert selector.observe(source, 10, now=4.01) == (None, True)


def test_selector_does_not_abandon_recent_phone_speech() -> None:
    selector = MicrophoneSelector(hold_s=5.0)
    source = "phone:voice"
    selector.observe(source, 90, voice=True, now=1.0)
    assert selector.observe(source, 90, voice=True, now=1.13) == (source, True)
    assert selector.observe(source, 10, now=4.0) == (source, False)
    # The silence hold is measured from the last real voice frame (1.13),
    # not from initial promotion or from the first poor-quality observation.
    assert selector.observe(source, 10, now=6.14) == (None, True)


def test_digital_silence_is_demoted_before_source_selection() -> None:
    runtime = RemoteMicRuntime()
    source = "phone:silent"
    metrics = {"score": 96.0, "rms": 0.1}
    assert runtime._apply_silence_fallback(source, metrics, now=1.0) == 96.0
    assert runtime._apply_silence_fallback(source, metrics, now=26.1) == 0.0
    assert metrics["score"] == 0.0
    metrics = {"score": 92.0, "rms": 900.0}
    assert runtime._apply_silence_fallback(source, metrics, now=27.0) == 92.0
    assert source not in runtime._quiet_since


def test_streaming_stt_start_never_blocks_the_audio_consumer() -> None:
    from reyes_agent.voice.stt import streaming

    transcriber = streaming.StreamingTranscriber(lambda _result: None)
    transcriber._run = lambda: time.sleep(0.2)
    started = time.perf_counter()
    assert transcriber.start(wait_timeout_s=0.0) is True
    elapsed = time.perf_counter() - started
    transcriber.close()
    assert elapsed < 0.05, f"socket startup blocked the audio worker for {elapsed:.3f}s"


def test_remote_runtime_shutdown_releases_its_audio_subscription() -> None:
    runtime = RemoteMicRuntime()
    runtime.set_command_handler(lambda *_args: {})
    manager = get_audio_manager()
    assert "remote-phone-turn" in manager.status()["consumers"]
    asyncio.run(runtime.shutdown())
    assert "remote-phone-turn" not in manager.status()["consumers"]


def test_quality_score_is_bounded_and_silence_does_not_disconnect() -> None:
    quality = AudioQuality()
    result = {}
    for index in range(12):
        result = quality.observe(b"\x00\x00" * 320, now=1 + index * 0.02)
    assert 65 <= result["score"] <= 100
    assert result["jitter_ms"] < 1
    assert "snr_db" in result


def test_client_transport_metrics_are_bounded_to_known_fields() -> None:
    runtime = RemoteMicRuntime()
    runtime.client_metrics("device", {"rtt_ms": 42, "jitter_ms": 4,
                           "packets_lost": 1, "packets_sent": 99,
                           "secret": "must-not-be-retained"})
    assert runtime._client_metrics["device"] == {
        "rtt_ms": 42, "jitter_ms": 4, "packets_lost": 1, "packets_sent": 99,
    }


def test_wake_parser_requires_prefix_and_wav_is_real() -> None:
    assert _WAKE.match("Hey ZENO, open my project").group(1) == "open my project"
    assert _WAKE.match("we should ask ZENO later") is None
    data = _wav(b"\x00\x00" * 320)
    assert data.startswith(b"RIFF") and b"WAVE" in data[:16]


def test_phone_page_is_audio_endpoint_not_a_second_assistant() -> None:
    page = (Path(__file__).parents[1] / "reyes_agent" / "static" / "mic.html").read_text("utf-8")
    assert "RTCPeerConnection" in page
    assert "getUserMedia" in page
    # Audio cleanup is REQUESTED, but conditionally: an external microphone
    # gets the raw stream, because Chrome's echo cancellation puts Android
    # into voice-communication mode, which routes to the BUILT-IN mic and
    # silenced the owner's OTG lav entirely (measured: peak RMS 5.7 against
    # 1377 for the phone's own mic). The built-in mic still gets the full
    # processing. What matters for THIS test is that the page asks for
    # cleanup at all rather than shipping raw audio unconditionally.
    assert "echoCancellation" in page
    assert "noiseSuppression" in page
    assert "SpeechRecognition" not in page
    assert "speechSynthesis" not in page
    assert "/api/phone/mic/offer" in page


def test_real_loopback_webrtc_delivers_audio_frames() -> None:
    async def scenario() -> None:
        import av
        from aiortc import MediaStreamTrack, RTCConfiguration, RTCPeerConnection, RTCSessionDescription

        class ToneTrack(MediaStreamTrack):
            kind = "audio"
            def __init__(self) -> None:
                super().__init__()
                self.pts = 0
            async def recv(self):
                await asyncio.sleep(0.02)
                frame = av.AudioFrame(format="s16", layout="mono", samples=960)
                frame.sample_rate = 48_000
                frame.pts = self.pts
                frame.time_base = Fraction(1, 48_000)
                self.pts += 960
                frame.planes[0].update((600).to_bytes(2, "little", signed=True) * 960)
                return frame

        runtime = RemoteMicRuntime()
        client = RTCPeerConnection(configuration=RTCConfiguration(iceServers=[]))
        client.addTrack(ToneTrack())
        offer = await client.createOffer()
        await client.setLocalDescription(offer)
        await runtime._wait_for_ice(client, 1.0)
        answer = await runtime.offer("integration-device", client.localDescription.sdp,
                                     client.localDescription.type)
        await client.setRemoteDescription(RTCSessionDescription(**answer))
        deadline = time.monotonic() + 3
        while runtime.status()["received_frames"] < 8 and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        assert runtime.status()["received_frames"] >= 8
        assert runtime.status()["transport"] == "WebRTC DTLS-SRTP/Opus"
        await client.close()
        await runtime.shutdown()

    asyncio.run(scenario())
