"""Deterministic Anthropic-compatible LLM stub for integration checks."""

import json
import time
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_error(404)
            return
        self._send_json({"status": "ok"})

    def do_POST(self) -> None:
        if self.path != "/v1/messages":
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length) or b"{}")
        prompt = json.dumps(request).lower()
        if "durable crash recovery" in prompt:
            time.sleep(8)
        if "critical evaluator" in prompt:
            content = '{"score": 0.95, "gaps": []}'
        else:
            content = (
                "def integration_smoke(value: str = 'ok') -> str:\n"
                "    return f'galaxz-integration:{value}'\n"
            )

        self._send_json(
            {
                "id": "msg_integration_stub",
                "type": "message",
                "role": "assistant",
                "model": request.get("model", "test-model"),
                "content": [{"type": "text", "text": content}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 10},
            }
        )

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_json(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
