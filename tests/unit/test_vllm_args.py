"""Unit tests: config/model.yaml is valid and renders the vLLM command we expect."""

import re

import pytest
import vllm_args
import yaml


def test_revision_is_pinned_sha(model_cfg):
    assert re.fullmatch(r"[0-9a-f]{40}", model_cfg["model"]["revision"])


def test_image_pinned_by_digest(model_cfg):
    ref = vllm_args.image_ref(model_cfg)
    assert re.search(r"@sha256:[0-9a-f]{64}$", ref), ref


def test_server_args_come_from_config(model_cfg, monkeypatch):
    monkeypatch.setenv("GPU_MEMORY_UTILIZATION", "0.1")  # must NOT leak into the shared function
    args = vllm_args.server_args(model_cfg)
    m, s = model_cfg["model"], model_cfg["serving"]
    assert args[0] == m["id"], "model must be the positional first argument"
    flags = dict(zip(args[1::2], args[2::2], strict=True))
    assert flags["--revision"] == m["revision"]
    assert flags["--tokenizer-revision"] == m["revision"]
    assert flags["--served-model-name"] == m["served_name"]
    assert flags["--dtype"] == s["dtype"]
    assert flags["--max-model-len"] == str(s["max_model_len"])
    assert flags["--gpu-memory-utilization"] == str(s["gpu_memory_utilization"])


def test_gpu_memory_override(model_cfg):
    flags = dict(zip(*[iter(vllm_args.server_args(model_cfg, "0.5")[1:])] * 2, strict=True))
    assert flags["--gpu-memory-utilization"] == "0.5"


def test_t4_compatible_dtype(model_cfg):
    # T4 (sm_75) has no bfloat16 support.
    if "T4" in model_cfg["hardware_profile"]["gpu"]:
        assert model_cfg["serving"]["dtype"] == "float16"


def test_load_rejects_unpinned_revision(tmp_path, repo_root):
    cfg = yaml.safe_load((repo_root / "config" / "model.yaml").read_text())
    cfg["model"]["revision"] = "main"
    bad = tmp_path / "model.yaml"
    bad.write_text(yaml.safe_dump(cfg))
    with pytest.raises(SystemExit):
        vllm_args.load(bad)


@pytest.mark.parametrize("name", ["smoke-v1", "smoke-v2"])
def test_prompt_set_is_well_formed(repo_root, name):
    ps = yaml.safe_load((repo_root / "app" / "prompts" / f"{name}.yaml").read_text())
    assert ps["version"] == name, "version field must match filename"
    assert 0 < ps.get("min_pass_rate", 1.0) <= 1
    ids = [p["id"] for p in ps["prompts"]]
    assert len(ids) == len(set(ids)), "prompt ids must be unique"
    for p in ps["prompts"]:
        assert p["content"].strip() and p["expect_any"]
