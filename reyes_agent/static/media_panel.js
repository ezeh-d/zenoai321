// ZENO live media panel -- an always-on mini card that shows what's playing
// and controls it. Consumes /api/media/stream (SSE) for real-time updates and
// POSTs to /api/media/command. Self-contained: injects its own styles and a
// fixed corner card; degrades to hidden when nothing is playing.
//
// Usage (from the HUD):  import { initMediaPanel } from "/static/media_panel.js";
//                        initMediaPanel();

function apiUrl(path) {
  // served from the same origin as the app; keep it absolute + simple
  return path;
}

const STYLE = `
#zeno-media-card{position:fixed;right:18px;bottom:18px;width:300px;z-index:9000;
  display:none;font-family:system-ui,Segoe UI,Roboto,sans-serif;color:#dff6ff;
  background:linear-gradient(145deg,rgba(6,18,26,.92),rgba(4,12,20,.92));
  border:1px solid rgba(64,196,255,.35);border-radius:14px;padding:12px;
  box-shadow:0 8px 30px rgba(0,0,0,.5),0 0 18px rgba(32,160,220,.18);
  backdrop-filter:blur(6px);transition:opacity .25s ease,transform .25s ease;
  opacity:0;transform:translateY(8px);}
#zeno-media-card.show{display:block;opacity:1;transform:translateY(0);}
#zeno-media-card .row{display:flex;gap:11px;align-items:center;}
#zeno-media-card .art{width:56px;height:56px;border-radius:9px;flex:0 0 auto;
  object-fit:cover;background:rgba(64,196,255,.12);border:1px solid rgba(64,196,255,.25);}
#zeno-media-card .meta{min-width:0;flex:1;}
#zeno-media-card .title{font-size:13.5px;font-weight:600;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis;}
#zeno-media-card .artist{font-size:11.5px;opacity:.72;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis;}
#zeno-media-card .src{font-size:9.5px;letter-spacing:.5px;text-transform:uppercase;
  opacity:.5;margin-top:2px;}
#zeno-media-card .bar{height:3px;border-radius:2px;background:rgba(64,196,255,.18);
  margin:10px 0 8px;overflow:hidden;}
#zeno-media-card .bar>i{display:block;height:100%;width:0;background:#40c4ff;
  box-shadow:0 0 8px rgba(64,196,255,.8);transition:width .5s linear;}
#zeno-media-card .ctrls{display:flex;justify-content:center;gap:16px;align-items:center;}
#zeno-media-card button{background:none;border:none;color:#dff6ff;cursor:pointer;
  font-size:17px;opacity:.85;padding:4px;line-height:1;border-radius:8px;}
#zeno-media-card button:hover{opacity:1;background:rgba(64,196,255,.12);}
#zeno-media-card .play{font-size:22px;}
`;

let els = null;
let source = null;
let anim = null;
let last = { position_s: 0, duration_s: 0, playing: false, at: 0, key: "" };

function build() {
  if (els) return els;
  const style = document.createElement("style");
  style.textContent = STYLE;
  document.head.appendChild(style);

  const card = document.createElement("div");
  card.id = "zeno-media-card";
  card.innerHTML = `
    <div class="row">
      <img class="art" alt="" />
      <div class="meta">
        <div class="title">--</div>
        <div class="artist"></div>
        <div class="src"></div>
      </div>
    </div>
    <div class="bar"><i></i></div>
    <div class="ctrls">
      <button class="prev" title="Previous">⏮</button>
      <button class="play" title="Play/Pause">⏯</button>
      <button class="next" title="Next">⏭</button>
    </div>
    <a class="connect" href="/api/media/spotify/connect" target="_blank"
       rel="noopener" style="display:none;font-size:10.5px;color:#1db954;
       text-align:center;margin-top:6px;text-decoration:none;opacity:.9;">
       ♫ Connect Spotify for search &amp; play</a>`;
  document.body.appendChild(card);

  els = {
    card,
    art: card.querySelector(".art"),
    title: card.querySelector(".title"),
    artist: card.querySelector(".artist"),
    src: card.querySelector(".src"),
    fill: card.querySelector(".bar>i"),
    prev: card.querySelector(".prev"),
    play: card.querySelector(".play"),
    next: card.querySelector(".next"),
  };
  els.prev.onclick = () => command("previous");
  els.next.onclick = () => command("next");
  els.play.onclick = () => command("toggle");
  return els;
}

async function command(action, extra = {}) {
  try {
    await fetch(apiUrl("/api/media/command"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, reference: "it", ...extra }),
    });
    // the SSE stream will push the resulting state; no optimistic redraw needed
  } catch (_e) { /* control is best-effort; ignore */ }
}

function render(active) {
  const e = build();
  if (!active || !active.title) {
    e.card.classList.remove("show");
    return;
  }
  const key = `${active.app_id}|${active.title}|${active.artist}`;
  e.title.textContent = active.title || "";
  e.artist.textContent = active.artist || "";
  e.src.textContent = active.source || "";
  e.play.textContent = active.playing ? "⏸" : "▶";
  if (key !== last.key) {
    // cache-bust art on track change
    e.art.src = apiUrl(`/api/media/art?app_id=${encodeURIComponent(active.app_id || "")}&v=${encodeURIComponent(key)}`);
    e.art.onerror = () => { e.art.style.visibility = "hidden"; };
    e.art.onload = () => { e.art.style.visibility = "visible"; };
  }
  last = {
    position_s: active.position_s || 0,
    duration_s: active.duration_s || 0,
    playing: !!active.playing,
    at: Date.now(),
    key,
  };
  e.card.classList.add("show");
  tick();
}

function tick() {
  if (!els) return;
  let pos = last.position_s;
  if (last.playing) pos += (Date.now() - last.at) / 1000;
  const pct = last.duration_s > 0 ? Math.min(100, (pos / last.duration_s) * 100) : 0;
  els.fill.style.width = pct.toFixed(1) + "%";
}

function onEvent(msg) {
  let obj;
  try { obj = JSON.parse(msg.data); } catch (_e) { return; }
  const payload = obj.payload || {};
  if (obj.type === "state") {
    render(payload.active || (payload.mini_card ? payload : null));
  } else if (obj.type === "track_changed") {
    render(payload.active || null);
  }
  // playback_changed / volume_changed arrive as a following state push too
}

async function refreshSpotifyConnect() {
  const e = build();
  const link = e.card.querySelector(".connect");
  if (!link) return;
  try {
    const s = await (await fetch(apiUrl("/api/media/spotify/status"))).json();
    // offer the entry point whenever Spotify isn't linked yet; the /connect
    // route either bounces to Spotify (client id set) or explains what to set
    link.style.display = s.connected ? "none" : "block";
  } catch (_e) { link.style.display = "none"; }
}

export function initMediaPanel() {
  if (source) return;                      // idempotent
  build();
  try {
    source = new EventSource(apiUrl("/api/media/stream"));
    source.onmessage = onEvent;
    source.onerror = () => { /* EventSource auto-reconnects */ };
  } catch (_e) { /* SSE unsupported -> panel stays hidden */ }
  // local progress animation between server pushes
  if (!anim) anim = setInterval(tick, 500);
  refreshSpotifyConnect();                 // show "Connect Spotify" if unlinked
}

export function stopMediaPanel() {
  if (source) { source.close(); source = null; }
  if (anim) { clearInterval(anim); anim = null; }
  if (els) els.card.classList.remove("show");
}
