# TODO - Next Update

## GPU Training Support
- [ ] Fix NVIDIA Container Toolkit for Docker Desktop (WSL2 backend)
  - Ensure latest NVIDIA GPU driver with WSL2 support is installed
  - Enable WSL2 GPU integration in Docker Desktop (Settings > Resources > WSL Integration)
  - Install `nvidia-container-toolkit` inside WSL2 distro if needed
  - Test with: `docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi`
- [ ] Add GPU reservation to `server` service in `docker-compose.yml`:
  ```yaml
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]
  ```
- [ ] Also fix the existing `deepseek-ocr` service (same GPU issue, currently not running)
- GPU device flag code is already in place in `kraken_training_service.py` (uses `-d cuda:0` for Kraken 5.x)
- Host GPU: NVIDIA RTX 2000 Ada Generation, 8GB VRAM
- PyTorch in container already has CUDA 12.1 compiled in

## Kraken Progress.py Patch
- [ ] Make the kraken `progress.py` patch persistent (currently lost on container recreate)
  - Option A: Add patch to `server/Dockerfile` (post-install `sed` or Python script)
  - Option B: Pin a fixed version of kraken/rich that doesn't have the bug
  - Bug: `rich.console.clear_live()` crashes with `IndexError: pop from empty list` when running ketos without a TTY
  - Patch location: `/opt/conda/lib/python3.8/site-packages/kraken/lib/progress.py` line 112
  - Fix: wrap `self._console.clear_live()` in `try/except IndexError`

## Training UX
- [ ] Add epoch count selector to training UI (currently hardcoded to 50)
- [ ] Show estimated training time based on line count
- [ ] Show real-time training progress (epoch, accuracy) in the UI during training

add export training data from the UI
Add eBL API