# One-command workflows. Targets are filled in as the build progresses (see docs/PLAN.md).
SHELL := /bin/bash
.DEFAULT_GOAL := help

KIND_CLUSTER ?= llm-platform

define todo
	@echo "TODO: '$@' is implemented in $(1) — see docs/PLAN.md"; exit 1
endef

.PHONY: help
help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

## --- Week 1: inference baseline ---
.PHONY: serve smoke test
serve: ## Run vLLM locally with the pinned model config
	$(call todo,Week 1 step 2)
smoke: ## Run API smoke tests against a running endpoint
	$(call todo,Week 1 step 3)
test: ## Run unit tests
	$(call todo,Week 1 step 3)

## --- Week 2: packaging, delivery, infrastructure ---
.PHONY: lint kind-up kind-down infra-up infra-down
lint: ## Lint Python, Helm chart, and manifests
	$(call todo,Week 2 step 7)
kind-up: ## Create local kind cluster
	$(call todo,Week 2 step 8)
kind-down: ## Delete local kind cluster
	$(call todo,Week 2 step 8)
infra-up: ## Terraform apply: AKS + GPU pool + budget alert
	$(call todo,Week 2 step 9)
infra-down: ## Terraform destroy: remove ALL billable Azure resources
	$(call todo,Week 2 step 9)

## --- Week 4: evidence ---
.PHONY: bench
bench: ## Run declared load-test scenario
	$(call todo,Week 4 step 15)
