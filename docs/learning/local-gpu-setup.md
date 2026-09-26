# Local GPU dev setup — Windows 11 + WSL2 + Docker (RTX A2000 8GB)

Goal: run the pinned vLLM image on the laptop GPU so Week 1 needs no cloud GPU.

## How GPU access works on WSL2
Windows owns the GPU. The **Windows** NVIDIA driver exposes it into WSL2 (`/usr/lib/wsl/lib`),
and Docker's NVIDIA runtime passes it into containers with `--gpus all`.
➡ **Never install an NVIDIA Linux driver inside WSL** — it breaks this path.

## One-time setup
1. **Windows NVIDIA driver** — update to the latest Studio/Enterprise driver for RTX A2000 Laptop.
   Check in PowerShell: `nvidia-smi` (note the driver version; the cu129 vLLM image needs ≥ 525).
2. **WSL2 + Ubuntu** — PowerShell (admin): `wsl --install -d Ubuntu-24.04`, then `wsl --update`.
3. **WSL memory** — create `%UserProfile%\.wslconfig`:
   ```ini
   [wsl2]
   memory=20GB
   swap=8GB
   ```
   then `wsl --shutdown`.
4. **Docker Desktop** — Settings → General: *Use WSL 2 based engine*; Resources → WSL integration: enable Ubuntu.
5. **Verify GPU in a container** (inside Ubuntu):
   ```bash
   docker run --rm --gpus all nvidia/cuda:12.9.1-base-ubuntu24.04 nvidia-smi
   ```
   You should see the RTX A2000.
6. **Tools inside Ubuntu**:
   ```bash
   sudo apt update && sudo apt install -y make python3-pip python3-venv jq git
   git clone https://github.com/zohaib85/MLOps-Project.git && cd MLOps-Project
   git checkout claude/sleepy-franklin-k8tnfj
   python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements-dev.txt
   ```
   Keep the repo in the Linux filesystem (`~/...`), not `/mnt/c/...` — much faster I/O.

## Run it
```bash
make serve      # pulls ~9 GB image once, downloads ~1 GB model into the hf-cache volume
make logs       # wait for "Application startup complete"
curl -s localhost:8000/health -o /dev/null -w "%{http_code}\n"   # 200
curl -s localhost:8000/v1/models | jq
curl -s localhost:8000/v1/chat/completions -H 'Content-Type: application/json' -d '{
  "model": "qwen2.5-0.5b-instruct",
  "messages": [{"role": "user", "content": "In one sentence, what is Kubernetes?"}],
  "temperature": 0, "max_tokens": 64
}' | jq
make stop
```

## Troubleshooting
| Symptom | Likely cause | Fix |
|---|---|---|
| `could not select device driver "" with capabilities: [[gpu]]` | Docker not using WSL2 / NVIDIA runtime | Recheck step 4, restart Docker Desktop |
| `CUDA out of memory` at startup | Laptop GPU shared with other apps | `make serve GPU_MEMORY_UTILIZATION=0.5`, close GPU apps |
| `No available memory for the cache blocks` | utilization too low for weights + KV cache | raise to 0.7, or lower `max_model_len` |
| Container exits, `nvidia-smi` fails in WSL | Linux driver installed in WSL | Remove it; rely on Windows driver |
| Very slow model download / load | Repo or cache under `/mnt/c` | Use Linux filesystem + named volume |

## Why the `hf-cache` named volume?
The model is downloaded once and reused across `make stop` / `make serve`. This is the local
equivalent of the model-cache PVC we'll use on AKS (ADR-0002).
