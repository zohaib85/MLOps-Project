# Evidence — Week 1 local inference baseline

**Date:** 2026-09-26 · **Purpose:** prove the pinned serving path works end to end before Kubernetes.
**Not a benchmark** — laptop GPU, development only.

## Environment
| Item | Value |
|---|---|
| Host | Windows 11 + WSL2 (Ubuntu 24.04), Docker Desktop |
| GPU | NVIDIA RTX A2000 8GB Laptop, driver 596.08 |
| Image | `docker.io/vllm/vllm-openai:v0.29.0-cu129@sha256:7ef5a35d1ef8ce2cf9d671dd91eec6e367c5849262e0362b4d3d4a26be0d87d2` |
| Model | `Qwen/Qwen2.5-0.5B-Instruct` @ `7ae557604adf67be50417f59c2c2f167def9a775`, float16, max_model_len 4096 |
| Local overrides | `GPU_MEMORY_UTILIZATION=0.60`, `VLLM_WSL2_ENABLE_PIN_MEMORY=1` |
| Prompt set | `smoke-v2` (min pass rate 0.8) |

## Result — `make smoke`
```
tests/smoke/test_api.py::test_health PASSED
tests/smoke/test_api.py::test_serves_expected_model PASSED
tests/smoke/test_api.py::test_unknown_model_rejected PASSED
tests/smoke/test_api.py::test_chat_response_shape PASSED
tests/smoke/test_api.py::test_max_tokens_respected PASSED
tests/smoke/test_api.py::test_deterministic_at_temperature_zero PASSED
tests/smoke/test_api.py::test_prompt_set_pass_rate PASSED
UserWarning: domain: expected one of ['kubernetes', 'k8s'], got 'Docker'
7 passed, 1 warning in 1.15s
```
Prompt-set pass rate: **4/5 (80%)** — at threshold.

## Issues found on the way (and how they were resolved)
| # | Symptom | Root cause | Resolution |
|---|---|---|---|
| 1 | `RuntimeError: operator torchvision::nms does not exist` at import | `v0.30.0-cu129` ships cu130 torch with cu129 torchvision ([vllm#56829](https://github.com/vllm-project/vllm/issues/56829)) | Pinned `v0.29.0-cu129`; no in-container patching |
| 2 | `RuntimeError: UVA is not available` | WSL2 disables pinned host memory; V2 model runner requires it | `VLLM_WSL2_ENABLE_PIN_MEMORY=1` set automatically on WSL only |
| 3 | Prompt `domain` failed → whole run failed | 0.5B model knowledge gap; per-prompt gating too strict for a statistical signal | `smoke-v2`: strict serving gates + aggregate quality gate |

## Takeaways
- Pin by digest *and* verify startup — a published release can be broken.
- Local and target platforms differ; keep platform-specific settings explicit and scoped.
- Gate serving correctness strictly; gate model quality statistically.
