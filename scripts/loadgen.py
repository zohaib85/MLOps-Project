"""Closed-loop load generator for the OpenAI-compatible endpoint.

N workers each send chat requests back-to-back for D seconds (synthetic prompts only), then print
throughput, error count and latency percentiles. Used to put traffic on the dashboard and to drive
alert drills; the Week 4 benchmark builds on it.

    python3 scripts/loadgen.py --base-url http://localhost:8000 --concurrency 4 --duration 60
"""

from __future__ import annotations

import argparse
import statistics
import threading
import time

import httpx
import vllm_args

PROMPTS = [
    "In one sentence, what is a Kubernetes Deployment?",
    "List three benefits of GitOps.",
    "Explain what a readiness probe does.",
    "What is the difference between a container image tag and a digest?",
]


def worker(client, url, model, max_tokens, stop_at, out, lock):
    i = 0
    while time.monotonic() < stop_at:
        body = {
            "model": model,
            "messages": [{"role": "user", "content": PROMPTS[i % len(PROMPTS)]}],
            "max_tokens": max_tokens,
            "temperature": 0,
        }
        t0 = time.monotonic()
        try:
            ok = client.post(url, json=body).status_code == 200
        except httpx.HTTPError:
            ok = False
        with lock:
            out.append((ok, time.monotonic() - t0))
        i += 1


def pct(sorted_vals, p):
    return sorted_vals[min(len(sorted_vals) - 1, int(p * len(sorted_vals)))] if sorted_vals else float("nan")


def main() -> None:
    cfg = vllm_args.load(vllm_args.DEFAULT_CONFIG)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--model", default=cfg["model"]["served_name"])
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--duration", type=float, default=60, help="seconds")
    ap.add_argument("--max-tokens", type=int, default=64)
    args = ap.parse_args()

    url = args.base_url.rstrip("/") + "/v1/chat/completions"
    results: list[tuple[bool, float]] = []
    lock = threading.Lock()
    stop_at = time.monotonic() + args.duration
    print(f"{args.concurrency} workers → {url} for {args.duration:.0f}s (model {args.model})")
    with httpx.Client(timeout=120) as client:
        job = (client, url, args.model, args.max_tokens, stop_at, results, lock)
        threads = [threading.Thread(target=worker, args=job) for _ in range(args.concurrency)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    lat = sorted(d for ok, d in results if ok)
    errors = sum(1 for ok, _ in results if not ok)
    print(f"requests: {len(results)}  errors: {errors}  throughput: {len(results) / args.duration:.2f} req/s")
    if lat:
        p50, p95, mean = pct(lat, 0.5), pct(lat, 0.95), statistics.fmean(lat)
        print(f"latency  p50 {p50:.3f}s  p95 {p95:.3f}s  mean {mean:.3f}s")


if __name__ == "__main__":
    main()
