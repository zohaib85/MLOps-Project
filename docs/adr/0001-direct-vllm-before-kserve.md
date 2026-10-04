# ADR-0001: Deploy vLLM directly before adopting KServe

- **Status:** Proposed — finalised in Week 4
- **Date:** 2026-09-26

## Context
We need to serve one open-weight instruct model on one GPU node profile. The build must expose GPU scheduling, startup, model caching, probes, batching, and metrics clearly enough to operate and explain them.

## Options considered
1. **Direct vLLM Deployment via Helm** — full visibility of mechanics, minimal control plane.
2. **KServe InferenceService (vLLM runtime)** — model lifecycle abstractions, but adds Knative/Istio or raw-deployment mode complexity.
3. **Managed endpoint (Azure ML online endpoint)** — least ops, least learning and portability.

## Decision
_To be confirmed with evidence from the build._

## Consequences
_TBD._

## When this decision would change
_TBD._
