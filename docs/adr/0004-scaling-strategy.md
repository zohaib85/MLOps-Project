# ADR-0004: Scaling strategy for GPU inference

- **Status:** Proposed — finalised in Week 4
- **Date:** 2026-09-26

## Context
One T4 GPU node, cost-sensitive, demo-window workloads. GPU nodes are expensive when idle and slow to cold-start (node provision + image pull + model load).

## Options considered
1. **Fixed single replica, GPU pool scaled to 0 manually between sessions** — predictable, cheapest to reason about.
2. **HPA on vLLM queue/request metrics + cluster autoscaler** — elastic, but cold starts of minutes.
3. **KEDA with scale-to-zero** — lowest idle cost, worst first-request latency.

## Decision
_To be confirmed with evidence from the build._

## Consequences
_TBD._

## When this decision would change
_TBD._
