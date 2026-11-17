"""
Turn a DeepSeek-OCR LoRA adapter into an Ollama model.

Ollama (on Windows) cannot import DeepSeek-OCR from safetensors, so instead we:

1. merge the LoRA into the base model's bf16 weights (only the weights LoRA touched);
2. copy Ollama's own deepseek-ocr GGUF and overwrite exactly those weights in the copy.
   Every target is found by name and checked byte for byte against the original
   weight before it is overwritten, so a different base or GGUF layout fails loudly
   instead of producing a broken model;
3. `ollama create` a model from the patched GGUF, with the base model's template and
   parameters. Names start with "deepseek-ocr-" so BEn sends them DeepSeek's own prompt.
"""
import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional

BASE_OLLAMA_MODEL = "deepseek-ocr:3b"

# HF module name -> GGUF tensor name (deepseekocr architecture in Ollama)
_ATTN = {"q_proj": "attn_q", "k_proj": "attn_k", "v_proj": "attn_v", "o_proj": "attn_output"}
_FFN = {"gate_proj": "gate", "up_proj": "up", "down_proj": "down"}


def ollama_model_name(model_name: str) -> str:
    """Ollama name for a trained model: lowercase, safe characters, deepseek-ocr- prefix."""
    slug = re.sub(r"[^a-z0-9._-]+", "-", model_name.lower()).strip("-.") or "trained"
    return slug if slug.startswith("deepseek-ocr") else f"deepseek-ocr-{slug}"


def _gguf_target(hf_key: str):
    """Map a language-model weight name to (gguf tensor name, expert index or None)."""
    m = re.fullmatch(r"model\.layers\.(\d+)\.self_attn\.(q_proj|k_proj|v_proj|o_proj)\.weight", hf_key)
    if m:
        return f"blk.{m[1]}.{_ATTN[m[2]]}.weight", None
    m = re.fullmatch(r"model\.layers\.(\d+)\.mlp\.experts\.(\d+)\.(gate_proj|up_proj|down_proj)\.weight", hf_key)
    if m:
        return f"blk.{m[1]}.ffn_{_FFN[m[3]]}_exps.weight", int(m[2])
    m = re.fullmatch(r"model\.layers\.(\d+)\.mlp\.shared_experts\.(gate_proj|up_proj|down_proj)\.weight", hf_key)
    if m:
        return f"blk.{m[1]}.ffn_{_FFN[m[2]]}_shexp.weight", None
    m = re.fullmatch(r"model\.layers\.(\d+)\.mlp\.(gate_proj|up_proj|down_proj)\.weight", hf_key)
    if m:
        return f"blk.{m[1]}.ffn_{_FFN[m[2]]}.weight", None
    return None, None


def find_ollama() -> Optional[str]:
    exe = shutil.which("ollama")
    if exe:
        return exe
    candidate = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    return str(candidate) if candidate.exists() else None


def _run(args, timeout=None) -> str:
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:3])} failed: {(result.stderr or result.stdout).strip()[-500:]}")
    return result.stdout


def _base_modelfile(ollama: str, log: Callable[[str], None]) -> str:
    """Modelfile of the base model; pulls the model first if it is not installed."""
    try:
        return _run([ollama, "show", BASE_OLLAMA_MODEL, "--modelfile"], timeout=60)
    except RuntimeError:
        log(f"Downloading {BASE_OLLAMA_MODEL} in Ollama (about 6.7 GB, once)...")
        _run([ollama, "pull", BASE_OLLAMA_MODEL])
        return _run([ollama, "show", BASE_OLLAMA_MODEL, "--modelfile"], timeout=60)


def export_adapter_to_ollama(
    adapter_dir: str,
    base_model_dir: str,
    ollama_name: str,
    work_dir: str,
    log: Callable[[str], None] = logging.info,
) -> dict:
    """Merge `adapter_dir` into the base weights, patch Ollama's GGUF and create `ollama_name`."""
    ollama = find_ollama()
    if not ollama:
        raise RuntimeError("Ollama is not installed (needed to run the trained model in BEn)")

    modelfile = _base_modelfile(ollama, log)
    from_lines = [l for l in modelfile.splitlines() if l.startswith("FROM ")]
    if len(from_lines) != 1:
        raise RuntimeError(f"Unexpected Modelfile for {BASE_OLLAMA_MODEL}: {len(from_lines)} FROM lines")
    base_gguf = from_lines[0][5:].strip()
    if not os.path.exists(base_gguf):
        raise RuntimeError(f"Ollama model file not found: {base_gguf}")

    config = json.loads((Path(adapter_dir) / "adapter_config.json").read_text(encoding="utf-8"))
    r, alpha = config["r"], config["lora_alpha"]
    scale = alpha / (r ** 0.5) if config.get("use_rslora") else alpha / r

    # 1. Copy Ollama's GGUF; the copy is patched in place. Absolute path: Ollama resolves
    # a relative FROM against the Modelfile's folder and otherwise takes it for a model name.
    work = Path(work_dir).resolve()
    work.mkdir(parents=True, exist_ok=True)
    patched = work / "model.gguf"
    log("Copying the Ollama base model...")
    shutil.copyfile(base_gguf, patched)

    try:
        merged_count = _patch_gguf(patched, adapter_dir, base_model_dir, scale, log)
        # Release the memory map, or Windows keeps the file locked
        import gc
        gc.collect()

        # 3. Create the Ollama model with the base model's template and parameters
        lines = [f"FROM {patched}"]
        lines += [l for l in modelfile.splitlines()
                  if l.startswith("TEMPLATE ") or l.startswith("PARAMETER ") or l.startswith("SYSTEM ")]
        mf_path = work / "Modelfile"
        mf_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        log(f"Creating Ollama model {ollama_name}...")
        _run([ollama, "create", ollama_name, "-f", str(mf_path)])
    finally:
        # Ollama keeps its own copy; ours is 6.7 GB
        import gc
        gc.collect()
        try:
            patched.unlink(missing_ok=True)
        except OSError as e:
            logging.warning(f"Could not delete {patched}: {e}")

    log(f"Ollama model {ollama_name} is ready")
    return {"ollama_model": ollama_name, "merged_weights": merged_count}


def _patch_gguf(patched: Path, adapter_dir: str, base_model_dir: str, scale: float,
                log: Callable[[str], None]) -> int:
    """Merge the LoRA into the base weights and write them into the GGUF copy.

    Kept in its own function so that every view into the memory map is gone when it returns."""
    import torch
    from safetensors import safe_open
    from gguf import GGUFReader

    reader = GGUFReader(str(patched), "r+")
    tensors = {t.name: t for t in reader.tensors}

    base_index = {}
    for bf in sorted(Path(base_model_dir).glob("*.safetensors")):
        with safe_open(str(bf), framework="pt") as f:
            for k in f.keys():
                base_index[k] = str(bf)

    with safe_open(str(Path(adapter_dir) / "adapter_model.safetensors"), framework="pt") as ad:
        a_keys = sorted(k for k in ad.keys() if k.endswith(".lora_A.weight"))
        log(f"Merging {len(a_keys)} trained weights into the Ollama model...")
        open_base = {}
        for i, a_key in enumerate(a_keys, 1):
            module = a_key[: -len(".lora_A.weight")]
            if module.startswith("base_model.model."):
                module = module[len("base_model.model."):]
            hf_key = module + ".weight"
            gguf_name, expert = _gguf_target(hf_key)
            if gguf_name is None or gguf_name not in tensors:
                raise RuntimeError(f"No matching Ollama weight for {hf_key}")
            tensor = tensors[gguf_name]
            if tensor.tensor_type.name != "BF16":
                raise RuntimeError(f"{gguf_name} is {tensor.tensor_type.name}, expected BF16")
            if hf_key not in base_index:
                raise RuntimeError(f"{hf_key} missing from the base model")

            path = base_index[hf_key]
            if path not in open_base:
                open_base[path] = safe_open(path, framework="pt")
            w = open_base[path].get_tensor(hf_key)
            if w.dtype != torch.bfloat16:
                raise RuntimeError(f"{hf_key} is {w.dtype}, expected bfloat16")

            target = tensor.data[expert] if expert is not None else tensor.data
            original = w.contiguous().view(torch.uint8).numpy()
            if target.shape != original.shape or not (target == original).all():
                raise RuntimeError(
                    f"{gguf_name}{'' if expert is None else f'[{expert}]'} does not match the base "
                    f"weight {hf_key}: the Ollama model and the training base differ"
                )

            lora_a = ad.get_tensor(a_key).float()
            lora_b = ad.get_tensor(a_key.replace(".lora_A.", ".lora_B.")).float()
            merged = (w.float() + scale * (lora_b @ lora_a)).to(torch.bfloat16)
            target[...] = merged.contiguous().view(torch.uint8).numpy()

            if i % 200 == 0:
                log(f"Merging trained weights into the Ollama model: {i}/{len(a_keys)}")

    reader.data.flush()
    mmap = getattr(reader.data, "_mmap", None)
    del target, tensor, tensors, reader
    if mmap is not None:
        try:
            mmap.close()
        except (BufferError, ValueError):
            pass  # still referenced; gc.collect() in the caller releases it
    return len(a_keys)


def delete_ollama_model(ollama_name: str) -> bool:
    ollama = find_ollama()
    if not ollama:
        return False
    try:
        _run([ollama, "rm", ollama_name], timeout=120)
        return True
    except Exception as e:
        logging.warning(f"Could not remove Ollama model {ollama_name}: {e}")
        return False
