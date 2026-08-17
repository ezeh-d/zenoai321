// One WebView2 capture -> one bounded backend AudioManager frame stream.
// This module never calls getUserMedia; it only copies the stream vad.js owns.

function pcm16k(frame, sourceRate) {
  const ratio = Math.max(1, Number(sourceRate || 16000) / 16000);
  const length = Math.max(1, Math.floor(frame.length / ratio));
  const out = new Int16Array(length);
  for (let i = 0; i < length; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(frame.length, Math.max(start + 1, Math.floor((i + 1) * ratio)));
    let sum = 0;
    for (let j = start; j < end; j++) sum += frame[j];
    const sample = Math.max(-1, Math.min(1, sum / (end - start)));
    out[i] = sample < 0 ? sample * 32768 : sample * 32767;
  }
  return out.buffer;
}

export function createAudioFrameClient({ vad, token }) {
  let socket = null, ready = false, reconnects = 0, reconnectTimer = null, wanted = false;
  const unsubscribe = vad.onPcmFrame((frame, rate) => {
    if (ready && socket?.readyState === WebSocket.OPEN) {
      try { socket.send(pcm16k(frame, rate)); } catch (_error) {}
    }
  });
  async function connect() {
    wanted = true;
    if (socket && socket.readyState < 2) return;
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    const current = new WebSocket(`${scheme}://${location.host}/api/audio/frames`);
    socket = current; ready = false;
    current.onopen = async () => current.send(JSON.stringify({
      token: String(await token() || ''), source: 'dashboard'
    }));
    current.onmessage = event => {
      try { ready = Boolean(JSON.parse(event.data).ready); if (ready) reconnects = 0; } catch (_error) {}
    };
    current.onclose = () => {
      if (socket === current) { socket = null; ready = false; }
      // A renderer/network pause must not permanently disable always-on
      // listening. Keep exactly one retry timer and cap the backoff at 30 s.
      if (wanted && !reconnectTimer) {
        reconnects += 1;
        const delay = Math.min(30000, 700 * (2 ** Math.min(6, reconnects - 1)));
        reconnectTimer = setTimeout(() => { reconnectTimer = null; void connect(); }, delay);
      }
    };
  }
  function close() {
    wanted = false; ready = false;
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    const current = socket; socket = null;
    if (current) try { current.close(1000, 'capture stopped'); } catch (_error) {}
  }
  return { connect, close, dispose() { close(); unsubscribe(); },
    status: () => ({ ready, reconnects, reconnect_pending: Boolean(reconnectTimer) }) };
}
