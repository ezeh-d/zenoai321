# ZENO Anywhere Live Desktop

ZENO Anywhere now uses an authenticated WebRTC session to show the Windows
desktop in the owner PWA. Desktop frames do not pass through ordinary HTTP and
are not stored by the gateway. The gateway carries only bounded, short-lived
SDP/ICE signalling and session status.

## Trust boundary

View-only requires all of the following:

1. a trusted owner browser session;
2. a paired, online Windows ZENO device;
3. `ZENO_LIVE_DESKTOP_ENABLED=true` on that Windows node; and
4. an unexpired live-desktop session.

Manual remote input additionally requires:

1. a recent owner fingerprint/passkey step-up;
2. ZENO Anywhere's global remote-control switch; and
3. `ZENO_LIVE_DESKTOP_CONTROL_ENABLED=true` locally on Windows.

The input data channel accepts only a fixed mouse/scroll/key/text schema. It
cannot carry shell commands, paths, clipboard contents or file-transfer
instructions. Stopping a session releases held mouse buttons and modifier
keys. The Windows dashboard and Mini Orb display an indicator while streaming,
and either the phone or the laptop can stop the peer.

## Internet connectivity

Direct ICE works only where the two peers can establish a route. Reliable use
across mobile carriers and restrictive NATs needs an operator-controlled TURN
service supplied as `ZENO_WEBRTC_ICE_SERVERS_JSON`. TURN credentials are
returned only to authenticated peers and must remain outside Git and the
public PWA bundle.

Example shape (use real secrets only in the deployment environment):

```json
[
  {
    "urls": ["turns:turn.example.com:5349"],
    "username": "short-lived-user",
    "credential": "short-lived-secret"
  }
]
```

Without that configuration the UI reports `DIRECT_ONLY` or `STUN_ONLY`; it
does not claim internet reachability that has not been proved.

## Performance and limitations

- Capture, encoding and remote input are lazy and live outside the GUI thread.
- One Windows peer and one bounded input worker may exist at a time.
- LOW/BALANCED/HIGH cap capture at 540p/720p/1080p and 12/20/24 target FPS;
  actual FPS is reported from the real track/receiver rather than invented.
- Quality steps down when the phone reports high packet loss or RTT.
- PC audio is reported unavailable until a measured WASAPI-loopback
  `MediaStreamTrack` exists. ZENO voice and phone push-to-talk continue to work.
- Windows secure-desktop/UAC screens, Ctrl+Alt+Delete, clipboard and file
  transfer are intentionally outside this channel.
- The live signalling authority is in-process and single-instance, matching
  the current SQLite gateway. Restarting the gateway ends the ephemeral peer.

## Shared agent presence

The phone, dashboard and Mini Orb project the same `AgentPresenceManager` plus
real Agent Runtime/Event Bus state. Explicitly summoning an agent changes only
conversation presence; it does not start a worker. A worker is created only
when real work is delegated. Hidden faces pause animation, the Mini Orb renders
at most three compact participants, and a full Council belongs in the Council
or Situation Room.
