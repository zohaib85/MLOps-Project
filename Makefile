# One-command workflows. Targets are filled in as the build progresses (see docs/PLAN.md).
SHELL := /bin/bash
.DEFAULT_GOAL := help

KIND_CLUSTER ?= llm-platform
HELM         ?= helm
RELEASE      ?= llm
NAMESPACE    ?= llm
HARNESS_IMAGE ?= llm-platform-harness:dev
CONFTEST     ?= conftest
KUBECONFORM  ?= kubeconform
ENVS         := kind aks
# Value files per environment (order matters: later files override earlier ones).
values_files = -f charts/vllm/values-model.yaml -f deploy/envs/$(1)/values.yaml \
  $(if $(wildcard deploy/envs/$(1)/harness-image.yaml),-f deploy/envs/$(1)/harness-image.yaml)
PYTHON       ?= python3
CONTAINER    ?= vllm-local
PORT         ?= 8000
# Laptop GPU (8GB, shared with desktop) — leave headroom. AKS uses the value in config/model.yaml.
GPU_MEMORY_UTILIZATION ?= 0.60
export GPU_MEMORY_UTILIZATION
# WSL2 disables pinned host memory by default; vLLM's V2 model runner needs it ("UVA is not available").
IS_WSL := $(shell grep -qi microsoft /proc/version 2>/dev/null && echo 1)
WSL_DOCKER_ARGS := $(if $(IS_WSL),-e VLLM_WSL2_ENABLE_PIN_MEMORY=1)
# Extra docker run flags, e.g. EXTRA_DOCKER_ARGS="-e VLLM_USE_V2_MODEL_RUNNER=0"
EXTRA_DOCKER_ARGS ?=

define todo
	@echo "TODO: '$@' is implemented in $(1) — see docs/PLAN.md"; exit 1
endef

.PHONY: help
help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

## --- Week 1: inference baseline ---
.PHONY: serve stop logs clean-local smoke test
serve: ## Run vLLM locally (Docker + GPU) from config/model.yaml
	@IMAGE=$$($(PYTHON) scripts/vllm_args.py --image) && \
	ARGS=$$($(PYTHON) scripts/vllm_args.py) && \
	echo "Starting $$IMAGE" && \
	{ docker rm -f $(CONTAINER) >/dev/null 2>&1 || true; } && \
	docker run -d --name $(CONTAINER) --gpus all --ipc=host \
	  -p 127.0.0.1:$(PORT):8000 \
	  -v hf-cache:/root/.cache/huggingface \
	  $(WSL_DOCKER_ARGS) $(EXTRA_DOCKER_ARGS) \
	  $$IMAGE $$ARGS && \
	echo "Loading model... follow with 'make logs'; ready when http://localhost:$(PORT)/health returns 200"
stop: ## Stop and remove the local vLLM container
	-docker rm -f $(CONTAINER)
logs: ## Follow local vLLM logs
	docker logs -f $(CONTAINER)
clean-local: stop ## Remove local container AND cached model weights (hf-cache volume)
	-docker volume rm hf-cache
smoke: ## Smoke-test a running endpoint (BASE_URL, default localhost:8000)
	$(PYTHON) -m pytest tests/smoke -v
test: ## Run unit tests (no server needed)
	$(PYTHON) -m pytest

## --- Week 2: packaging, delivery, infrastructure ---
.PHONY: values chart-lint validate policy-test harness-image kind-up kind-down kind-deploy kind-test kind-smoke lint infra-up infra-down
values: ## Regenerate charts/vllm/values-model.yaml from config/model.yaml
	$(PYTHON) scripts/render_chart_values.py
chart-lint: ## helm lint the chart for every environment
	$(foreach e,$(ENVS),$(HELM) lint --strict charts/vllm $(call values_files,$(e)) &&) true
validate: ## Render each env; check schemas (kubeconform) and policy (conftest)
	$(foreach e,$(ENVS),$(HELM) template $(RELEASE) charts/vllm -n $(NAMESPACE) $(call values_files,$(e)) \
	  | $(KUBECONFORM) -strict -summary -ignore-missing-schemas - && \
	  $(HELM) template $(RELEASE) charts/vllm -n $(NAMESPACE) $(call values_files,$(e)) \
	  | $(CONFTEST) test -p policy - &&) true
policy-test: ## Unit-test the Rego policies
	$(CONFTEST) verify -p policy
harness-image: ## Build the harness image (smoke tests + mock server)
	docker build -t $(HARNESS_IMAGE) -f app/Dockerfile .
kind-up: ## Create local kind cluster
	kind create cluster --name $(KIND_CLUSTER) --wait 120s
	kubectl config current-context
kind-down: ## Delete local kind cluster
	kind delete cluster --name $(KIND_CLUSTER)
kind-deploy: harness-image ## Build + load harness image, helm install the chart (mock engine) on kind
	@test "$$(kubectl config current-context)" = "kind-$(KIND_CLUSTER)" || \
	  { echo "kubectl context is not kind-$(KIND_CLUSTER) — refusing to deploy"; exit 1; }
	kind load docker-image $(HARNESS_IMAGE) --name $(KIND_CLUSTER)
	$(HELM) upgrade --install $(RELEASE) charts/vllm -n $(NAMESPACE) --create-namespace \
	  $(call values_files,kind) --wait --timeout 5m
kind-test: ## helm test: in-cluster client reaches /health and /v1/models
	$(HELM) test $(RELEASE) -n $(NAMESPACE) --logs
kind-smoke: ## Port-forward and run smoke tests (quality gate skipped: mock is not a model)
	@kubectl -n $(NAMESPACE) port-forward svc/$(RELEASE)-vllm 8000:8000 >/dev/null 2>&1 & PF=$$!; \
	sleep 3; $(PYTHON) -m pytest tests/smoke -v -k "not pass_rate"; RC=$$?; kill $$PF; exit $$RC
lint: chart-lint ## ruff (Python) + helm lint + generated-values drift check
	ruff check .
	ruff format --check .
	$(PYTHON) scripts/render_chart_values.py --check
infra-up: ## Terraform apply: AKS + GPU pool + budget alert
	$(call todo,Week 2 step 9)
infra-down: ## Terraform destroy: remove ALL billable Azure resources
	$(call todo,Week 2 step 9)

## --- Week 4: evidence ---
.PHONY: bench
bench: ## Run declared load-test scenario
	$(call todo,Week 4 step 15)
