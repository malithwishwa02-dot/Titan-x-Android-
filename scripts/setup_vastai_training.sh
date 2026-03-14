#!/bin/bash
# Titan V11.3 — Vast.ai Training Environment Setup
# Run this on the Vast.ai GPU instance (RTX 5060 16GB)
# to install all dependencies for model fine-tuning.
#
# Usage:
#   ssh -p 28704 root@ssh2.vast.ai 'bash -s' < setup_vastai_training.sh
#   OR copy to instance and run: bash setup_vastai_training.sh

set -e
echo "=============================================="
echo "  Titan AI Training Environment Setup"
echo "  Vast.ai GPU Instance"
echo "=============================================="

# 1. System deps
echo "[1/6] Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq git curl wget python3-pip python3-venv > /dev/null 2>&1
echo "  Done."

# 2. Create venv for training (keeps Ollama env clean)
echo "[2/6] Creating Python virtual environment..."
VENV_DIR="/opt/titan/training-venv"
mkdir -p /opt/titan/models /opt/titan/data/trajectories
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
pip install --upgrade pip setuptools wheel > /dev/null 2>&1
echo "  Venv: $VENV_DIR"

# 3. Install training stack
echo "[3/6] Installing training dependencies (unsloth, trl, transformers)..."
pip install "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git" \
    --no-deps > /dev/null 2>&1 || true
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121 \
    > /dev/null 2>&1 || true
pip install transformers datasets accelerate peft trl bitsandbytes \
    sentencepiece protobuf scipy Pillow pandas scikit-learn \
    > /dev/null 2>&1
echo "  Done."

# 4. Install unsloth properly (after torch)
echo "[4/6] Installing unsloth (LoRA acceleration)..."
pip install "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git" \
    > /dev/null 2>&1 || {
    echo "  WARNING: unsloth install failed, falling back to standard PEFT"
    echo "  Training will work but ~2x slower"
}

# 5. Verify GPU
echo "[5/6] Verifying GPU access..."
python3 -c "
import torch
print(f'  PyTorch: {torch.__version__}')
print(f'  CUDA available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'  GPU: {torch.cuda.get_device_name(0)}')
    print(f'  VRAM: {torch.cuda.get_device_properties(0).total_mem / 1e9:.1f} GB')
else:
    print('  WARNING: No GPU detected! Training will be very slow.')
"

# 6. Verify imports
echo "[6/6] Verifying training imports..."
python3 -c "
ok = True
for mod in ['transformers', 'datasets', 'peft', 'trl', 'accelerate', 'bitsandbytes']:
    try:
        __import__(mod)
        print(f'  {mod}: OK')
    except ImportError as e:
        print(f'  {mod}: MISSING ({e})')
        ok = False

try:
    from unsloth import FastLanguageModel
    print(f'  unsloth: OK')
except ImportError:
    print(f'  unsloth: MISSING (will use standard PEFT)')

if ok:
    print('\n  All core dependencies installed successfully!')
else:
    print('\n  Some dependencies missing - check errors above')
"

echo ""
echo "=============================================="
echo "  Setup complete!"
echo "  Activate venv: source $VENV_DIR/bin/activate"
echo "  Run training:  python /opt/titan-v11.3-device/scripts/train_titan_models.py --task stats"
echo "=============================================="
