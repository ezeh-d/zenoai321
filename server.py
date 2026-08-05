"""
REYES mobile bridge — a tiny, dependency-free HTTP API.

Run:  python server.py            (listens on 0.0.0.0:8765)
Then from your phone on the SAME Wi-Fi, open  http://<computer-ip>:8765
or POST JSON {"message": "..."} to  http://<computer-ip>:8765/chat

Uses only the standard library so there's nothing extra to install. For a
public/hardened deployment, put this behind a reverse proxy with TLS + auth.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "0.0.0.0"
PORT = 8765

_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>REYES</title><style>
body{font-family:system-ui;background:#0b0f14;color:#e6edf3;margin:0;padding:16px}
h1{color:#37e0ff;font-weight:600;letter-spacing:2px}
#log{white-space:pre-wrap;line-height:1.5;margin:12px 0}
.u{color:#8bffb0}.r{color:#37e0ff}
input{width:72%;padding:12px;border-radius:10px;border:1px solid #22303c;background:#0f151c;color:#e6edf3}
button{padding:12px 16px;border:0;border-radius:10px;background:#37e0ff;color:#00232b;font-weight:700}
</style></head><body>
<h1>REYES</h1><div id="log"></div>
<input id="m" placeholder="Talk to REYES..." autofocus>
<button onclick="send()">Send</button>
<script>
const log=document.getElementById('log'),m=document.getElementById('m');
function add(c,t){log.innerHTML+=`<div class="${c}">${c=='u'?'you › ':'reyes › '}${t}</div>`;window.scrollTo(0,9e9);}
async function send(){const t=m.value.trim();if(!t)return;add('u',t);m.value='';
 try{const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:t})});
 const d=await r.json();add('r',d.reply||d.error||'(no reply)');}catch(e){add('r','network error');}}
m.addEventListener('keydown',e=>{if(e.key=='Enter')send();});
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # quiet default logging
        pass

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send(200, _PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/status":
            body = json.dumps({"status": "online", "service": "REYES"}).encode()
            self._send(200, body, "application/json")
        else:
            self._send(404, b'{"error":"not found"}', "application/json")

    def do_POST(self) -> None:
        if self.path != "/chat":
            self._send(404, b'{"error":"not found"}', "application/json")
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            message = (json.loads(raw or b"{}").get("message") or "").strip()
        except json.JSONDecodeError:
            self._send(400, b'{"error":"bad json"}', "application/json")
            return
        if not message:
            self._send(400, b'{"error":"empty message"}', "application/json")
            return
        try:
            from brain import think  # lazy: the shared JARVIS brain
            reply = think(message)
        except Exception as e:  # pragma: no cover - depends on live stack
            reply = f"[REYES backend error: {e}]"
        self._send(200, json.dumps({"reply": reply}).encode("utf-8"),
                   "application/json")


def serve(host: str = HOST, port: int = PORT) -> None:
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"REYES mobile bridge on http://{host}:{port}  "
          f"(open it from your phone on the same network)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()


if __name__ == "__main__":
    serve()
