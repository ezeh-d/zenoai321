"""Measured local WebRTC transport benchmark; no provider or fake result."""

from __future__ import annotations

import asyncio
from fractions import Fraction
import json
from pathlib import Path
import sys
import time

import av
from aiortc import MediaStreamTrack, RTCConfiguration, RTCPeerConnection, RTCSessionDescription

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reyes_agent.remote_mic.runtime import RemoteMicRuntime


class ToneTrack(MediaStreamTrack):
    kind = "audio"
    def __init__(self) -> None:
        super().__init__()
        self.pts = 0
    async def recv(self):
        await asyncio.sleep(0.02)
        frame = av.AudioFrame(format="s16", layout="mono", samples=960)
        frame.sample_rate = 48_000
        frame.pts, frame.time_base = self.pts, Fraction(1, 48_000)
        self.pts += 960
        frame.planes[0].update((500).to_bytes(2, "little", signed=True) * 960)
        return frame


async def main() -> None:
    runtime = RemoteMicRuntime()
    client = RTCPeerConnection(configuration=RTCConfiguration(iceServers=[]))
    client.addTrack(ToneTrack())
    started = time.perf_counter()
    offer = await client.createOffer()
    await client.setLocalDescription(offer)
    await runtime._wait_for_ice(client, 1.0)
    answer = await runtime.offer("benchmark", client.localDescription.sdp,
                                 client.localDescription.type)
    await client.setRemoteDescription(RTCSessionDescription(**answer))
    negotiated = time.perf_counter()
    while runtime.status()["received_frames"] < 10 and time.perf_counter() - started < 5:
        await asyncio.sleep(0.01)
    finished = time.perf_counter()
    status = runtime.status()
    print(json.dumps({
        "negotiation_ms": round((negotiated - started) * 1000, 2),
        "ten_frames_ms_from_offer": round((finished - started) * 1000, 2),
        "received_frames": status["received_frames"],
        "selected_source": status["selector"]["selected"],
        "transport": status["transport"],
    }, indent=2))
    await client.close()
    await runtime.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
