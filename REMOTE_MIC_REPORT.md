# ZENO Remote Phone Microphone — Phase 1 Report

Date: 2026-08-11

## Delivered

- One authenticated phone-as-microphone path using WebRTC DTLS-SRTP and Opus.
- Existing passkey/device/session registry reused; no second identity store.
- New paired devices receive the narrow `remote_audio_send` capability. It is
  checked at offer, telemetry and status routes, and can be removed locally.
- Audio is decoded/resampled once to 16 kHz mono PCM and published into the
  existing bounded `AudioManager`. The phone never runs ZENO's brain or TTS.
- Event-driven quality scoring and hysteresis select one source. Disconnect,
  two seconds of sustained poor quality, session expiry, lock or revocation
  safely restore the local WebView2 microphone.
- The phone `/mic` page requests one browser microphone, applies browser echo
  cancellation/noise suppression/AGC, shows the browser's real connection
  state, and sends bounded WebRTC telemetry every five seconds while active.
- The desktop settings panel can pair, approve, lock/revoke and inspect phones
  and see the real remote-microphone source/frame state.
- Remote VAD, speaker verification, Deepgram STT, command execution and PC
  ElevenLabs playback reuse the existing services and managed workers.

## Measured verification

- `aiortc 1.13.0` and `av 14.2.0` import in the project virtual environment.
- Latest real loopback DTLS-SRTP/Opus negotiation: **147.82 ms**.
- Ten real decoded/resampled frames from offer start: **1,164.91 ms**.
- Selected source in the measured run: `phone:benchmark`.
- Targeted security/remote-access/human-companion/latency suite: **52 passed**.
- A separate startup/window/Phase 21/Phase 22/Mini Orb/microphone/VAD/visual
  stability matrix passed **81**, for **133 distinct passing checks** in this
  delivery, plus the final network-quality regression (**134 distinct**).
  Pytest collects 663 maintained tests after test discovery was
  corrected to ignore archived interactive demos. The complete 663-test run
  exceeded its 15-minute command limit without producing a final result, so it
  is not reported as passed or failed.
- The dedicated WebRTC integration test sends media through two real
  `RTCPeerConnection` instances; it is not a mocked success.
- Python compilation passed. `/mic`, `/phone`, and dashboard JavaScript parsed.
- After the production desktop restart, the native host was responding; the
  Mini Orb remained the selected local owner and advanced 838 to 871 frames
  in two seconds with queue 0, drops 0 and consumer errors 0. `/mic` returned
  HTTP 200 and live remote-mic health reported aiortc ready/standby.
- The restarted local-safe `hello` path returned in 751.66 ms and its exact
  cached ElevenLabs audio returned in 399.49 ms (1,151.15 ms sequential server
  time to audio bytes). The cache-only thinking acknowledgement was 221.75 ms.
- A live unauthenticated WebRTC offer returned HTTP 401, created zero peers,
  and left `local-webview2` selected. The timed-out all-suite pytest child was
  detected and explicitly cleaned up; no pytest Python process remained.

## 1.5-second response truth

The media path itself becomes useful inside the 1.5-second budget. Safe exact
social replies and cached progress speech remain local/cache-only. Arbitrary
answer completion cannot be guaranteed in 1.5 seconds: the configured cloud
provider was previously measured at 5.403–15.914 seconds and clip-final STT is
also network-bound. ZENO therefore provides a fast audible acknowledgement
when a real wake command has been recognized, while the actual bounded turn
continues. It does not mislabel provider wait as local thinking.

## Deployment limit (not hidden)

This machine currently has `REMOTE_ACCESS_ENABLED=false`, no configured
`ZENO_PHONE_PUBLIC_HOST`, and no Cloudflare Tunnel config. Mobile browsers
require HTTPS for `getUserMedia`; ZENO intentionally does not expose its full
desktop API on an insecure LAN socket. The implementation and local encrypted
media path are tested, but a physical phone cannot connect until the owner
configures the existing HTTPS Phone Companion boundary and pairs that phone.

Phase 1 uses host/direct ICE suitable for a reachable local network. TURN,
internet-grade NAT traversal, multiple simultaneous selected phones, native
background/locked-phone capture and remote setup are not claimed.
