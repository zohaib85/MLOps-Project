"""Minimal OpenAI-compatible stub for clusters without a GPU (kind, CI).

Implements just enough of vLLM's surface — /health, /v1/models, /v1/chat/completions,
/metrics — to exercise the chart's Service, probes, NetworkPolicy, storage and monitoring.
/metrics uses vLLM's metric names (a subset of observability/vllm-metrics-v0.29.0.txt), so
dashboards and alert rules can be tested on kind. Drill knobs: MOCK_LATENCY_S (added delay per
chat request) and MOCK_ERROR_RATE (fraction of chat requests answered with HTTP 500).
It is NOT a model: answers are canned. Never use it for quality or performance results.
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SERVED_NAME = os.environ.get("MOCK_SERVED_NAME", "mock-model")
ROOT = os.environ.get("MOCK_ROOT", "mock/mock-model")
STARTUP_DELAY_S = float(os.environ.get("MOCK_STARTUP_DELAY_S", "0"))
PORT = int(os.environ.get("PORT", "8000"))
LATENCY_S = float(os.environ.get("MOCK_LATENCY_S", "0"))
ERROR_RATE = float(os.environ.get("MOCK_ERROR_RATE", "0"))
REPLY = "This is a mock response from the llm-platform test stub."
LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 40.0)


class Metrics:
    """Thread-safe counters/histograms rendered in the Prometheus text format (no client library)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.http: dict[tuple[str, str, str], int] = {}  # (handler, method, status class) -> count
        self.counters = {"vllm:prompt_tokens_total": 0, "vllm:generation_tokens_total": 0}
        self.hists = {
            n: {"buckets": [0] * len(LATENCY_BUCKETS), "sum": 0.0, "count": 0}
            for n in ("vllm:e2e_request_latency_seconds", "vllm:time_to_first_token_seconds")
        }
        self.running = 0

    def http_done(self, handler: str, method: str, code: int) -> None:
        key = (handler, method, f"{code // 100}xx")
        with self.lock:
            self.http[key] = self.http.get(key, 0) + 1

    def observe(self, name: str, value: float) -> None:
        with self.lock:
            h = self.hists[name]
            for i, le in enumerate(LATENCY_BUCKETS):
                if value <= le:
                    h["buckets"][i] += 1
            h["sum"] += value
            h["count"] += 1

    def add(self, name: str, n: int) -> None:
        with self.lock:
            self.counters[name] += n

    def render(self) -> str:
        lbl = f'model_name="{SERVED_NAME}",engine="0"'
        out = []
        with self.lock:
            out.append("# TYPE http_requests_total counter")
            for (handler, method, status), v in sorted(self.http.items()):
                labels = f'handler="{handler}",method="{method}",status="{status}"'
                out.append(f"http_requests_total{{{labels}}} {v}")
            for name, v in self.counters.items():
                out += [f"# TYPE {name.removesuffix('_total')} counter", f"{name}{{{lbl}}} {v}"]
            kv = min(1.0, self.running * 0.1)  # pretend each in-flight request holds 10% of the KV cache
            gauges = {"vllm:num_requests_running": self.running, "vllm:num_requests_waiting": 0}
            gauges["vllm:kv_cache_usage_perc"] = kv
            for name, v in gauges.items():
                out += [f"# TYPE {name} gauge", f"{name}{{{lbl}}} {v}"]
            for name, h in self.hists.items():
                out.append(f"# TYPE {name} histogram")
                for le, c in zip(LATENCY_BUCKETS, h["buckets"], strict=True):
                    out.append(f'{name}_bucket{{{lbl},le="{le}"}} {c}')
                out.append(f'{name}_bucket{{{lbl},le="+Inf"}} {h["count"]}')
                out.append(f"{name}_sum{{{lbl}}} {h['sum']}")
                out.append(f"{name}_count{{{lbl}}} {h['count']}")
        return "\n".join(out) + "\n"


METRICS = Metrics()
HANDLERS = {"/health", "/v1/models", "/v1/chat/completions", "/metrics"}


class Handler(BaseHTTPRequestHandler):
    server_version = "llm-platform-mock/1"

    def log_message(self, fmt, *args):  # keep logs quiet and structured
        print(json.dumps({"path": self.path, "status": args[1] if len(args) > 1 else None}))

    def _send(self, code: int, body: dict | str, ctype: str = "application/json") -> None:
        raw = body if isinstance(body, str) else json.dumps(body)
        data = raw.encode()
        if self.path in HANDLERS:
            METRICS.http_done(self.path, self.command, code)
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
            return self._send(200, METRICS.render(), "text/plain; version=0.0.4")
        self._send(404, {"error": {"message": "not found"}})

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            return self._send(404, {"error": {"message": "not found"}})
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if req.get("model") != SERVED_NAME:
            return self._send(404, {"error": {"message": f"The model `{req.get('model')}` does not exist."}})
        start = time.monotonic()
        with METRICS.lock:
            METRICS.running += 1
        try:
            if LATENCY_S:
                time.sleep(LATENCY_S)
            if random.random() < ERROR_RATE:  # noqa: S311 — fault injection, not security
                return self._send(500, {"error": {"message": "mock: injected failure (MOCK_ERROR_RATE)"}})
            self._complete(req, start)
        finally:
            with METRICS.lock:
                METRICS.running -= 1

    def _complete(self, req: dict, start: float) -> None:
        words = REPLY.split()
        max_tokens = int(req.get("max_tokens") or 64)
        out = words[:max_tokens]
        prompt_tokens = sum(len(m.get("content", "").split()) for m in req.get("messages", []))
        elapsed = time.monotonic() - start
        METRICS.observe("vllm:time_to_first_token_seconds", elapsed)
        METRICS.observe("vllm:e2e_request_latency_seconds", elapsed)
        METRICS.add("vllm:prompt_tokens_total", prompt_tokens)
        METRICS.add("vllm:generation_tokens_total", len(out))
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
