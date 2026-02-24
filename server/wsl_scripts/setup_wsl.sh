#!/bin/bash
# Setup script for Qwen3-VL in WSL2
# Run this once to install all dependencies

set -e

echo "=========================================="
echo "Setting up Qwen3-VL environment in WSL2"
echo "=========================================="

# Check CUDA
echo "Checking CUDA..."
if command -v nvidia-smi &> /dev/null; then
    nvidia-smi
else
    echo "WARNING: nvidia-smi not found. GPU may not be available."
fi

# Create virtual environment
VENV_DIR="$HOME/qwen3_venv"
echo "Creating virtual environment at $VENV_DIR..."

if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

# Upgrade pip
pip install --upgrade pip

# Install PyTorch with CUDA
echo "Installing PyTorch with CUDA support..."
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121

# Install Unsloth (fast LoRA training)
echo "Installing Unsloth..."
pip install "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git"

# Install other dependencies
echo "Installing other dependencies..."
pip install transformers accelerate bitsandbytes
pip install datasets trl peft
pip install pillow

# Verify installation
echo ""
echo "=========================================="
echo "Verifying installation..."
echo "=========================================="

python3 -c "
import torch
print(f'PyTorch version: {torch.__version__}')
print(f'CUDA available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'GPU: {torch.cuda.get_device_name(0)}')
    print(f'VRAM: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB')
"

python3 -c "
from unsloth import FastVisionModel
print('Unsloth installed successfully!')
"

echo ""
echo "=========================================="
echo "Setup complete!"
echo "=========================================="
echo ""
echo "To activate the environment, run:"
echo "  source $VENV_DIR/bin/activate"
echo ""
echo "To test OCR:"
echo "  python3 qwen3_ocr.py '{\"model_id\": \"Qwen/Qwen3-VL-4B\", \"use_4bit\": true, \"image_base64\": \"...\", \"prompt\": \"OCR this\"}'"
echo ""
echo "To train:"
echo "  python3 qwen3_train.py --data_path /path/to/data.jsonl --output_dir ./output"
