"""Tiny protocol fixture for the official MCP client regression test.

Keeping the fixture dependency-free separates client startup latency from a
second copy of the full SDK importing in a child process on an 8 GiB machine.
"""

import json
import sys


def send(identifier, result) -> None:
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": identifier, "result": result}) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    try:
        request = json.loads(line)
    except json.JSONDecodeError:
        continue
    identifier = request.get("id")
    method = request.get("method")
    if identifier is None:
        continue
    if method == "initialize":
        send(identifier, {
            "protocolVersion": request.get("params", {}).get("protocolVersion", "2025-11-25"),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "zeno-phase2-test", "version": "1"},
        })
    elif method == "tools/list":
        send(identifier, {"tools": [{
            "name": "echo", "description": "test echo",
            "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}},
            "annotations": {"readOnlyHint": True},
        }]})
    elif method == "tools/call":
        text = str(request.get("params", {}).get("arguments", {}).get("text", ""))
        payload = {"echo": text, "token": "fixture-secret-must-be-redacted"}
        send(identifier, {"content": [{"type": "text", "text": json.dumps(payload)}],
                          "structuredContent": payload, "isError": False})
    else:
        send(identifier, {})
