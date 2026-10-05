"""Tiny stdio MCP server used by Quasar tests. Not a real MCP implementation."""
import json
import sys
import time

TOOLS = [
    {"name": "echo", "description": "Echo text", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}},
    {"name": "fail", "description": "Always reports an error", "inputSchema": {"type": "object"}},
    {"name": "slow", "description": "Sleeps", "inputSchema": {"type": "object"}},
    {"name": "crash", "description": "Exits the process", "inputSchema": {"type": "object"}},
]


def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    rid = request.get("id")
    if rid is None:  # notification
        continue
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "fake", "version": "0"}}})
    elif method == "tools/list":
        cursor = request.get("params", {}).get("cursor")
        if cursor is None:
            send({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS[:2], "nextCursor": "page2"}})
        else:
            send({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS[2:]}})
    elif method == "tools/call":
        params = request["params"]
        name, args = params["name"], params.get("arguments", {})
        if name == "echo":
            send({"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": args.get("text", "")}], "isError": False}})
        elif name == "fail":
            send({"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": "boom"}], "isError": True}})
        elif name == "slow":
            time.sleep(5)
            send({"jsonrpc": "2.0", "id": rid, "result": {"content": [], "isError": False}})
        elif name == "crash":
            sys.exit(1)
        else:
            send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": f"unknown tool {name}"}})
    else:
        send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "method not found"}})
