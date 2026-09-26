# ADR-0003: GitOps security boundary between CI and the cluster

- **Status:** Proposed — finalised in Week 4
- **Date:** 2026-09-26

## Context
CI must be able to release changes, but a compromised CI runner must not grant cluster access. Releases must be auditable and reversible.

## Options considered
1. **Pull-based: CI publishes image + commits digest to Git; Argo CD in-cluster reconciles** — CI holds no kubeconfig.
2. **Push-based: CI runs helm upgrade with cluster credentials** — simpler, broader blast radius.
3. **Argo CD Image Updater writes digests back to Git** — less CI logic, another controller with Git write access.

## Decision
_To be confirmed with evidence from the build._

## Consequences
_TBD._

## When this decision would change
_TBD._
