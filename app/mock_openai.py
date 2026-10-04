"""Minimal OpenAI-compatible stub for clusters without a GPU (kind, CI).

Implements just enough of vLLM's surface — /health, /v1/models, /v1/chat/completions,
/metrics — to exercise the chart's Service, probes, NetworkPolicy and storage.
It is NOT a model: answers are canned. Never use it for quality or performance results.
"""

from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SERVED_NAME = os.environ.get("MOCK_SERVED_NAME", "mock-model")
ROOT = os.environ.get("MOCK_ROOT", "mock/mock-model")
STARTUP_DELAY_S = float(os.environ.get("MOCK_STARTUP_DELAY_S", "0"))
PORT = int(os.environ.get("PORT", "8000"))
REPLY = "This is a mock response from the llm-platform test stub."

REQUESTS = {"ok": 0, "error": 0}


class Handler(BaseHTTPRequestHandler):
    server_version = "llm-platform-mock/1"

    def log_message(self, fmt, *args):  # keep logs quiet and structured
        print(json.dumps({"path": self.path, "status": args[1] if len(args) > 1 else None}))

    def _send(self, code: int, body: dict | str, ctype: str = "application/json") -> None:
        raw = body if isinstance(body, str) else json.dumps(body)
        data = raw.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, {})
        if self.path == "/v1/models":
            return self._send(
                200,
                {
                    "object": "list",
                    "data": [
                        {"id": SERVED_NAME, "object": "model", "root": ROOT, "owned_by": "llm-platform-mock"}
                    ],
                },
            )
        if self.path == "/metrics":
            return self._send(
                200,
                "".join(f'mock_requests_total{{result="{k}"}} {v}\n' for k, v in REQUESTS.items()),
                "text/plain; version=0.0.4",
            )
        self._send(404, {"error": {"message": "not found"}})

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            return self._send(404, {"error": {"message": "not found"}})
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if req.get("model") != SERVED_NAME:
            REQUESTS["error"] += 1
            return self._send(404, {"error": {"message": f"The model `{req.get('model')}` does not exist."}})
        words = REPLY.split()
        max_tokens = int(req.get("max_tokens") or 64)
        out = words[:max_tokens]
        prompt_tokens = sum(len(m.get("content", "").split()) for m in req.get("messages", []))
        REQUESTS["ok"] += 1
        self._send(
            200,
            {
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": SERVED_NAME,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": " ".join(out)},
                        "finish_reason": "length" if len(words) > max_tokens else "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": len(out),
                    "total_tokens": prompt_tokens + len(out),
                },
            },
        )


def main() -> None:
    if STARTUP_DELAY_S:
        print(json.dumps({"event": "simulated_model_load", "seconds": STARTUP_DELAY_S}))
        time.sleep(STARTUP_DELAY_S)  # port closed meanwhile → startup probe keeps failing
    print(json.dumps({"event": "ready", "served_name": SERVED_NAME, "port": PORT}))
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
