# Service level objectives

Scope: the OpenAI-compatible chat endpoint (`POST /v1/chat/completions`) of the `llm-vllm` Service,
during the demo/evaluation window. Prompts are synthetic; there are no external users — these SLOs
exist to practise the method and to drive the alerts and drills.

| SLI (what we measure) | Source metric | SLO (target) | Window |
|---|---|---|---|
| **Availability** — share of chat requests not answered with 5xx | `http_requests_total{handler="/v1/chat/completions"}` by `status` class | **99%** | rolling 30 days (demo: per session) |
| **Latency** — p95 end-to-end request latency | `vllm:e2e_request_latency_seconds` histogram | **≤ 5 s** at the benchmark's target concurrency | 5 m windows, 10 m sustained |
| *(watch, no SLO)* Time to first token p95 | `vllm:time_to_first_token_seconds` | — | — |

Values live in `charts/vllm/values.yaml → metrics.slo` and feed the alert rules directly.
The latency objective is provisional until the T4 baseline run; it will be set from the benchmark
(p95 at the chosen concurrency plus headroom) and recorded in an ADR.

## Error budget
99% availability ⇒ **1% error budget**: in 10,000 requests, 100 may fail.
4xx (bad requests, unknown model) don't count — they are client errors, not unavailability.

## Alerting policy (why these alerts)
| Alert | Fires when | Severity | Why this shape |
|---|---|---|---|
| `LLMErrorBudgetFastBurn` | error ratio > 14.4 × 1% over **1 h and 5 m** | critical | Google SRE multi-window burn rate: 14.4× burns 2% of a 30-day budget in 1 h. The 5 m window makes it resolve quickly once fixed |
| `LLMLatencyP95High` | p95 > 5 s for 10 m | warning | Direct objective check; 10 m avoids paging on a single slow batch |
| `LLMEndpointDown` | no healthy target for 5 m | critical | Symptom-based: catches what the ratio alert can't (no traffic ⇒ no errors) |
| `LLMQueueBacklog`, `LLMKVCacheSaturated` | sustained queue / cache > 90% | warning | Leading indicators — latency SLO is about to be missed |
| `LLMPodRestarting`, `LLMPodPending` | restarts > 2 in 15 m / Pending 10 m | warning | Cause-based helpers that point the runbook at the fix |

A slow-burn alert (e.g. 6× over 6 h) is deliberately omitted: lab sessions are a few hours long.

## Recording rules
`llm:requests:rate5m`, `llm:errors:ratio_rate5m`, `llm:errors:ratio_rate1h`,
`llm:e2e_latency_seconds:p95_5m`, `llm:ttft_seconds:p95_5m`, `llm:generation_tokens:rate5m` —
pre-computed once every 30 s so alerts (and ad-hoc queries) are cheap and consistent.
