"""Smoke tests against a live endpoint. Run: `make smoke` (BASE_URL defaults to localhost:8000)."""

import time
import warnings


def chat(client, model, content, max_tokens=48):
    t0 = time.perf_counter()
    r = client.post(
        "/v1/chat/completions",
        json={
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0,
            "max_tokens": max_tokens,
        },
    )
    return r, time.perf_counter() - t0


def test_health(client):
    assert client.get("/health").status_code == 200


def test_serves_expected_model(client, model_cfg):
    r = client.get("/v1/models")
    assert r.status_code == 200
    models = {m["id"]: m for m in r.json()["data"]}
    served = model_cfg["model"]["served_name"]
    assert served in models, f"expected {served}, got {list(models)}"
    # vLLM reports the underlying HF repo as `root` — guards against serving the wrong weights.
    assert models[served].get("root") == model_cfg["model"]["id"]


def test_unknown_model_rejected(client):
    r, _ = chat(client, "does-not-exist", "hi", max_tokens=1)
    assert r.status_code == 404


def test_chat_response_shape(client, model_cfg):
    r, _ = chat(client, model_cfg["model"]["served_name"], "Say hello.", max_tokens=16)
    assert r.status_code == 200
    body = r.json()
    assert body["model"] == model_cfg["model"]["served_name"]
    choice = body["choices"][0]
    assert choice["message"]["content"].strip()
    assert choice["finish_reason"] in ("stop", "length")
    u = body["usage"]
    assert u["prompt_tokens"] > 0 and u["completion_tokens"] > 0
    assert u["total_tokens"] == u["prompt_tokens"] + u["completion_tokens"]


def test_max_tokens_respected(client, model_cfg):
    r, _ = chat(
        client, model_cfg["model"]["served_name"], "Count from 1 to 100 separated by commas.", max_tokens=5
    )
    body = r.json()
    assert body["usage"]["completion_tokens"] <= 5
    assert body["choices"][0]["finish_reason"] == "length"


def test_deterministic_at_temperature_zero(client, model_cfg):
    name = model_cfg["model"]["served_name"]
    a = chat(client, name, "Name three primary colors.")[0].json()["choices"][0]["message"]["content"]
    b = chat(client, name, "Name three primary colors.")[0].json()["choices"][0]["message"]["content"]
    assert a == b


def test_prompt_set_pass_rate(client, model_cfg, prompt_set, run_record):
    """Quality gate: aggregate pass rate, not per-prompt. Every answer is recorded."""
    failures = []
    for p in prompt_set["prompts"]:
        r, latency = chat(
            client, model_cfg["model"]["served_name"], p["content"], max_tokens=prompt_set["max_tokens"]
        )
        assert r.status_code == 200, f"{p['id']}: HTTP {r.status_code}"
        answer = r.json()["choices"][0]["message"]["content"]
        passed = any(k.lower() in answer.lower() for k in p["expect_any"])
        run_record["results"].append(
            {
                "id": p["id"],
                "passed": passed,
                "latency_s": round(latency, 3),
                "completion_tokens": r.json()["usage"]["completion_tokens"],
                "answer": answer,
            }
        )
        if not passed:
            failures.append(f"{p['id']}: expected one of {p['expect_any']}, got {answer!r}")
            warnings.warn(failures[-1], stacklevel=2)

    rate = 1 - len(failures) / len(prompt_set["prompts"])
    run_record["pass_rate"] = rate
    minimum = prompt_set.get("min_pass_rate", 1.0)
    assert rate >= minimum, f"pass rate {rate:.0%} < {minimum:.0%}:\n" + "\n".join(failures)
