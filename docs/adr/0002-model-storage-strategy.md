# ADR-0002: Model weight storage and caching

- **Status:** Proposed — finalised in Week 4
- **Date:** 2026-09-26

## Context
Weights must never be committed to Git. Pod start time on a GPU node is dominated by model download + load. The model revision must be pinned and reproducible.

## Options considered
1. **Download from Hugging Face at startup into a PVC cache (Azure Disk)** — simple, fast restarts on same node.
2. **Azure Files (RWX) shared cache** — shareable across replicas, slower reads.
3. **Bake weights into the container image** — immutable, but huge images and slow pulls.
4. **Init container pulling from Azure Blob** — decoupled from HF availability, more moving parts.

## Decision
_To be confirmed with evidence from the build._

## Consequences
_TBD._

## When this decision would change
_TBD._
