#!/bin/bash
# Titan V11.3 — Incremental Retraining Script
# Runs periodically (via cron) to retrain models with new trajectory data.
#
# Cron setup (daily at 3 AM):
#   echo "0 3 * * * /opt/titan-v11.3-device/scripts/retrain_incremental.sh >> /var/log/titan-retrain.log 2>&1" | crontab -
#
# What it does:
#   1. Check if enough new trajectories accumulated since last training
#   2. Export training data (action + vision JSONL)
#   3. Retrain action model with LoRA
#   4. Retrain vision model with LoRA
#   5. Export to GGUF and register with Ollama
#   6. Log results

set -e

TITAN_DIR="${TITAN_DIR:-/opt/titan-v11.3-device}"
DATA_DIR="${TITAN_DATA:-/opt/titan/data}/trajectories"
MODEL_DIR="/opt/titan/models"
VENV_DIR="/opt/titan/training-venv"
LOG_FILE="/var/log/titan-retrain.log"
LOCK_FILE="/tmp/titan-retrain.lock"
MIN_NEW_TRAJECTORIES=20  # minimum new trajectories before retraining

# Prevent concurrent runs
if [ -f "$LOCK_FILE" ]; then
    pid=$(cat "$LOCK_FILE")
    if kill -0 "$pid" 2>/dev/null; then
        echo "[$(date)] Retrain already running (PID $pid), skipping"
        exit 0
    fi
fi
echo $$ > "$LOCK_FILE"
trap "rm -f $LOCK_FILE" EXIT

echo ""
echo "=============================================="
echo "[$(date)] Titan Incremental Retrain Starting"
echo "=============================================="

# Activate training venv
if [ -d "$VENV_DIR" ]; then
    source "$VENV_DIR/bin/activate"
else
    echo "  Training venv not found at $VENV_DIR"
    echo "  Run setup_vastai_training.sh first"
    exit 1
fi

# Add core to PYTHONPATH
export PYTHONPATH="$TITAN_DIR/core:$TITAN_DIR/server:$PYTHONPATH"

# 1. Check trajectory count
echo "[1/5] Checking trajectory data..."
STATS=$(python3 "$TITAN_DIR/scripts/train_titan_models.py" --task stats --data "$DATA_DIR" 2>&1)
echo "$STATS"

COMPLETED=$(echo "$STATS" | grep "Completed:" | awk '{print $2}')
COMPLETED=${COMPLETED:-0}

# Check against last training count
LAST_COUNT_FILE="$MODEL_DIR/.last_train_count"
LAST_COUNT=0
if [ -f "$LAST_COUNT_FILE" ]; then
    LAST_COUNT=$(cat "$LAST_COUNT_FILE")
fi

NEW_COUNT=$((COMPLETED - LAST_COUNT))
echo "  New trajectories since last train: $NEW_COUNT (threshold: $MIN_NEW_TRAJECTORIES)"

if [ "$NEW_COUNT" -lt "$MIN_NEW_TRAJECTORIES" ]; then
    echo "  Not enough new data. Skipping retrain."
    echo "[$(date)] Skipped: $NEW_COUNT new trajectories (need $MIN_NEW_TRAJECTORIES)"
    exit 0
fi

# 2. Export training data
echo "[2/5] Exporting training data..."
python3 -c "
import sys; sys.path.insert(0, '$TITAN_DIR/core')
from trajectory_logger import TrainingDataExporter
e = TrainingDataExporter('$DATA_DIR')
a = e.export_action_training()
v = e.export_vision_training()
print(f'  Action examples: {a}')
print(f'  Vision examples: {v}')
"

# 3. Train action model
echo "[3/5] Training action model..."
python3 "$TITAN_DIR/scripts/train_titan_models.py" \
    --task action \
    --data "$DATA_DIR" \
    --output "$MODEL_DIR/titan-agent-7b-lora" \
    --epochs 2 --lr 1e-4 --rank 16 --batch-size 2 --grad-accum 4 \
    2>&1 || {
    echo "  Action model training FAILED"
}

# 4. Train vision model (if enough examples)
VISION_COUNT=$(wc -l < "$DATA_DIR/vision_training.jsonl" 2>/dev/null || echo "0")
if [ "$VISION_COUNT" -ge 50 ]; then
    echo "[4/5] Training vision model..."
    python3 "$TITAN_DIR/scripts/train_titan_models.py" \
        --task vision \
        --data "$DATA_DIR" \
        --output "$MODEL_DIR/titan-screen-7b-lora" \
        --epochs 2 --lr 1e-4 --rank 16 --batch-size 1 --grad-accum 8 \
        2>&1 || {
        echo "  Vision model training FAILED"
    }
else
    echo "[4/5] Skipping vision model (only $VISION_COUNT examples, need 50+)"
fi

# 5. Export to GGUF + register with Ollama
echo "[5/5] Exporting to GGUF and registering with Ollama..."
if [ -d "$MODEL_DIR/titan-agent-7b-lora" ]; then
    python3 "$TITAN_DIR/scripts/train_titan_models.py" \
        --task export \
        --model "$MODEL_DIR/titan-agent-7b-lora" \
        --output "$MODEL_DIR/titan-agent-7b-gguf" \
        2>&1 || echo "  GGUF export failed for action model"

    # Register with Ollama
    if [ -f "$MODEL_DIR/titan-agent-7b-gguf/Modelfile" ]; then
        cd "$MODEL_DIR/titan-agent-7b-gguf"
        ollama create titan-agent:7b -f Modelfile 2>&1 || echo "  Ollama registration failed"
        echo "  Registered titan-agent:7b with Ollama"
    fi
fi

if [ -d "$MODEL_DIR/titan-screen-7b-lora" ]; then
    python3 "$TITAN_DIR/scripts/train_titan_models.py" \
        --task export \
        --model "$MODEL_DIR/titan-screen-7b-lora" \
        --output "$MODEL_DIR/titan-screen-7b-gguf" \
        2>&1 || echo "  GGUF export failed for vision model"

    if [ -f "$MODEL_DIR/titan-screen-7b-gguf/Modelfile" ]; then
        cd "$MODEL_DIR/titan-screen-7b-gguf"
        ollama create titan-screen:7b -f Modelfile 2>&1 || echo "  Ollama registration failed"
        echo "  Registered titan-screen:7b with Ollama"
    fi
fi

# Save training count
echo "$COMPLETED" > "$LAST_COUNT_FILE"

echo ""
echo "=============================================="
echo "[$(date)] Retrain complete!"
echo "  Trajectories used: $COMPLETED"
echo "  Models: titan-agent:7b, titan-screen:7b"
echo "=============================================="
