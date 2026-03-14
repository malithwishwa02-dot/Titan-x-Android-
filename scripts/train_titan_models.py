#!/usr/bin/env python3
"""
Titan V11.3 — AI Model Training Script
========================================
Fine-tunes vision and action models using LoRA on collected trajectories.

Two training modes:
  1. ACTION model — text-only, learns screen-context → JSON action mapping
     Base: Qwen/Qwen2.5-7B-Instruct (or configurable)
  2. VISION model — multimodal, learns screenshot → UI description mapping
     Base: Qwen/Qwen2-VL-7B-Instruct (or configurable)

Uses Unsloth for 2-4x faster LoRA training on consumer GPUs (16GB+).

Usage:
    # Train action model
    python train_titan_models.py --task action \
        --data /opt/titan/data/trajectories \
        --output /opt/titan/models/titan-agent-7b-lora \
        --epochs 3 --lr 2e-4 --rank 16

    # Train vision model
    python train_titan_models.py --task vision \
        --data /opt/titan/data/trajectories \
        --output /opt/titan/models/titan-screen-7b-lora \
        --epochs 3 --lr 2e-4 --rank 16

    # Export to GGUF for Ollama
    python train_titan_models.py --task export \
        --model /opt/titan/models/titan-agent-7b-lora \
        --output /opt/titan/models/titan-agent-7b.Q4_K_M.gguf

    # Stats only
    python train_titan_models.py --task stats --data /opt/titan/data/trajectories
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("titan.train")

# Add core to path for TrainingDataExporter
CORE_DIR = Path(__file__).parent.parent / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))


# ═══════════════════════════════════════════════════════════════════════
# DATASET LOADING
# ═══════════════════════════════════════════════════════════════════════

def load_action_dataset(data_dir: str, min_success_rate: float = 0.5) -> List[Dict]:
    """Load action training examples from trajectory directory."""
    from trajectory_logger import TrainingDataExporter
    exporter = TrainingDataExporter(trajectory_dir=data_dir)

    # Export to temp JSONL
    tmp_path = Path(data_dir) / "_action_train_tmp.jsonl"
    count = exporter.export_action_training(output_path=str(tmp_path),
                                            min_success_rate=min_success_rate)
    if count == 0:
        logger.warning("No action training examples found")
        return []

    examples = []
    with open(tmp_path) as f:
        for line in f:
            try:
                examples.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    tmp_path.unlink(missing_ok=True)
    logger.info(f"Loaded {len(examples)} action training examples")
    return examples


def load_vision_dataset(data_dir: str) -> List[Dict]:
    """Load vision training examples from trajectory directory."""
    from trajectory_logger import TrainingDataExporter
    exporter = TrainingDataExporter(trajectory_dir=data_dir)

    tmp_path = Path(data_dir) / "_vision_train_tmp.jsonl"
    count = exporter.export_vision_training(output_path=str(tmp_path))
    if count == 0:
        logger.warning("No vision training examples found")
        return []

    examples = []
    with open(tmp_path) as f:
        for line in f:
            try:
                examples.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    tmp_path.unlink(missing_ok=True)
    logger.info(f"Loaded {len(examples)} vision training examples")
    return examples


def format_action_for_sft(examples: List[Dict]) -> List[Dict]:
    """Convert action examples to SFT chat format for training."""
    formatted = []
    for ex in examples:
        instruction = ex.get("instruction", "")
        output = ex.get("output", "")
        if not instruction or not output:
            continue
        formatted.append({
            "conversations": [
                {"role": "system", "content": (
                    "You are an AI agent controlling an Android phone. "
                    "Analyze the screen and decide the next action. "
                    "Respond with ONLY a JSON object: "
                    '{\"action\": \"...\", \"x\": N, \"y\": N, \"text\": \"...\", \"reason\": \"...\"}'
                )},
                {"role": "user", "content": instruction},
                {"role": "assistant", "content": output},
            ]
        })
    return formatted


def format_vision_for_sft(examples: List[Dict], base_dir: str) -> List[Dict]:
    """Convert vision examples to multimodal SFT format."""
    formatted = []
    for ex in examples:
        convs = ex.get("conversations", [])
        img_path = ex.get("image", "")
        if not convs or not img_path:
            continue
        full_path = Path(base_dir) / img_path
        if not full_path.exists():
            continue
        formatted.append({
            "image": str(full_path),
            "conversations": convs,
        })
    return formatted


# ═══════════════════════════════════════════════════════════════════════
# ACTION MODEL TRAINING (TEXT-ONLY LoRA)
# ═══════════════════════════════════════════════════════════════════════

def train_action_model(data_dir: str, output_dir: str,
                       base_model: str = "Qwen/Qwen2.5-7B-Instruct",
                       epochs: int = 3, lr: float = 2e-4,
                       rank: int = 16, alpha: int = 32,
                       batch_size: int = 2, grad_accum: int = 4,
                       max_seq_len: int = 2048):
    """Fine-tune action planning model with LoRA."""
    logger.info(f"=== ACTION MODEL TRAINING ===")
    logger.info(f"Base: {base_model} | LoRA r={rank} α={alpha}")
    logger.info(f"Epochs: {epochs} | LR: {lr} | Batch: {batch_size}×{grad_accum}")

    # Load data
    raw = load_action_dataset(data_dir)
    if len(raw) < 10:
        logger.error(f"Only {len(raw)} examples — need at least 10 for training. Collect more trajectories first.")
        return False

    dataset = format_action_for_sft(raw)
    logger.info(f"Formatted {len(dataset)} training examples")

    # Split train/val 90/10
    split = int(len(dataset) * 0.9)
    train_data = dataset[:split]
    val_data = dataset[split:]
    logger.info(f"Train: {len(train_data)} | Val: {len(val_data)}")

    try:
        from trl import SFTTrainer, SFTConfig
        from datasets import Dataset
    except ImportError as e:
        logger.error(f"Missing core training dependencies: {e}")
        return False

    # --- Try unsloth first (2x faster), fall back to standard PEFT ---
    _use_unsloth = False
    model = None
    tokenizer = None

    try:
        import warnings
        warnings.filterwarnings("ignore")
        from unsloth import FastLanguageModel
        logger.info(f"Loading {base_model} via unsloth (4-bit QLoRA)...")
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=base_model,
            max_seq_length=max_seq_len,
            dtype=None,
            load_in_4bit=True,
        )
        model = FastLanguageModel.get_peft_model(
            model,
            r=rank,
            lora_alpha=alpha,
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                            "gate_proj", "up_proj", "down_proj"],
            lora_dropout=0.05,
            bias="none",
            use_gradient_checkpointing="unsloth",
        )
        _use_unsloth = True
        logger.info("Unsloth loaded successfully (2x faster training)")
    except Exception as e:
        logger.warning(f"Unsloth unavailable ({e.__class__.__name__}), falling back to standard PEFT")
        _use_unsloth = False

    if not _use_unsloth:
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
            from peft import LoraConfig, get_peft_model, TaskType, prepare_model_for_kbit_training
        except ImportError as e:
            logger.error(f"Missing standard PEFT dependencies: {e}")
            return False

        logger.info(f"Loading {base_model} via standard PEFT (4-bit via bitsandbytes)...")
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
        )
        model = AutoModelForCausalLM.from_pretrained(
            base_model,
            quantization_config=bnb_config,
            device_map="auto",
            trust_remote_code=True,
        )
        tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        model = prepare_model_for_kbit_training(model)
        lora_config = LoraConfig(
            r=rank,
            lora_alpha=alpha,
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                            "gate_proj", "up_proj", "down_proj"],
            lora_dropout=0.05,
            bias="none",
            task_type=TaskType.CAUSAL_LM,
        )
        model = get_peft_model(model, lora_config)
        model.print_trainable_parameters()
        logger.info("Standard PEFT model loaded")

    # Format dataset for SFTTrainer
    def _format_chat(example):
        text = tokenizer.apply_chat_template(
            example["conversations"], tokenize=False, add_generation_prompt=False
        )
        return {"text": text}

    train_ds = Dataset.from_list(train_data).map(_format_chat)
    val_ds = Dataset.from_list(val_data).map(_format_chat) if val_data else None

    # Training config
    os.makedirs(output_dir, exist_ok=True)
    training_args = SFTConfig(
        output_dir=output_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=grad_accum,
        learning_rate=lr,
        weight_decay=0.01,
        warmup_ratio=0.1,
        lr_scheduler_type="cosine",
        logging_steps=5,
        save_strategy="epoch",
        eval_strategy="epoch" if val_ds else "no",
        fp16=True,
        max_seq_length=max_seq_len,
        dataset_text_field="text",
        seed=42,
        report_to="none",
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        args=training_args,
    )

    logger.info("Starting training...")
    trainer.train()

    # Save LoRA adapter
    logger.info(f"Saving LoRA adapter to {output_dir}")
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)

    # Save training metadata
    meta = {
        "base_model": base_model,
        "task": "action",
        "lora_rank": rank,
        "lora_alpha": alpha,
        "epochs": epochs,
        "learning_rate": lr,
        "train_examples": len(train_data),
        "val_examples": len(val_data),
        "max_seq_length": max_seq_len,
    }
    with open(Path(output_dir) / "titan_training_meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    logger.info("Action model training COMPLETE")
    return True


# ═══════════════════════════════════════════════════════════════════════
# VISION MODEL TRAINING (MULTIMODAL LoRA)
# ═══════════════════════════════════════════════════════════════════════

def train_vision_model(data_dir: str, output_dir: str,
                       base_model: str = "Qwen/Qwen2-VL-7B-Instruct",
                       epochs: int = 3, lr: float = 2e-4,
                       rank: int = 16, alpha: int = 32,
                       batch_size: int = 1, grad_accum: int = 8,
                       max_seq_len: int = 2048):
    """Fine-tune vision model for Android screen understanding with LoRA."""
    logger.info(f"=== VISION MODEL TRAINING ===")
    logger.info(f"Base: {base_model} | LoRA r={rank} α={alpha}")

    # Load data
    raw = load_vision_dataset(data_dir)
    if len(raw) < 10:
        logger.error(f"Only {len(raw)} examples — need at least 10. Collect more trajectories first.")
        return False

    dataset = format_vision_for_sft(raw, data_dir)
    logger.info(f"Formatted {len(dataset)} vision training examples")

    split = int(len(dataset) * 0.9)
    train_data = dataset[:split]
    val_data = dataset[split:]
    logger.info(f"Train: {len(train_data)} | Val: {len(val_data)}")

    try:
        from unsloth import FastVisionModel
        from trl import SFTTrainer, SFTConfig
        from datasets import Dataset
    except ImportError as e:
        logger.error(f"Missing dependencies: {e}")
        logger.error("Install: pip install 'unsloth[vision]' transformers datasets trl")
        return False

    # Load vision model
    logger.info(f"Loading {base_model} with 4-bit quantization...")
    model, tokenizer = FastVisionModel.from_pretrained(
        model_name=base_model,
        max_seq_length=max_seq_len,
        dtype=None,
        load_in_4bit=True,
    )

    # Apply LoRA to vision model
    model = FastVisionModel.get_peft_model(
        model,
        r=rank,
        lora_alpha=alpha,
        finetune_vision_layers=True,
        finetune_language_layers=True,
        finetune_attention_modules=True,
        finetune_mlp_modules=True,
        lora_dropout=0.05,
        bias="none",
        use_gradient_checkpointing="unsloth",
    )

    # Build dataset with images
    from PIL import Image

    def _load_example(example):
        img = Image.open(example["image"]).convert("RGB")
        convs = example["conversations"]
        messages = []
        for c in convs:
            if c["role"] == "user":
                messages.append({
                    "role": "user",
                    "content": [
                        {"type": "image", "image": img},
                        {"type": "text", "text": c["content"]},
                    ],
                })
            else:
                messages.append({"role": "assistant", "content": c["content"]})
        return {"messages": messages, "images": [img]}

    logger.info("Loading images for vision training...")
    processed_train = []
    for ex in train_data:
        try:
            processed_train.append(_load_example(ex))
        except Exception as e:
            logger.debug(f"Skip image: {e}")
            continue

    if len(processed_train) < 5:
        logger.error("Not enough valid image examples after filtering")
        return False

    train_ds = Dataset.from_list(processed_train)

    os.makedirs(output_dir, exist_ok=True)
    training_args = SFTConfig(
        output_dir=output_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=grad_accum,
        learning_rate=lr,
        weight_decay=0.01,
        warmup_ratio=0.1,
        lr_scheduler_type="cosine",
        logging_steps=5,
        save_strategy="epoch",
        fp16=True,
        max_seq_length=max_seq_len,
        seed=42,
        report_to="none",
        remove_unused_columns=False,
        dataset_kwargs={"skip_prepare_dataset": True},
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train_ds,
        args=training_args,
        data_collator=None,  # unsloth handles this
    )

    logger.info("Starting vision model training...")
    trainer.train()

    logger.info(f"Saving LoRA adapter to {output_dir}")
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)

    meta = {
        "base_model": base_model,
        "task": "vision",
        "lora_rank": rank,
        "lora_alpha": alpha,
        "epochs": epochs,
        "learning_rate": lr,
        "train_examples": len(processed_train),
        "max_seq_length": max_seq_len,
    }
    with open(Path(output_dir) / "titan_training_meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    logger.info("Vision model training COMPLETE")
    return True


# ═══════════════════════════════════════════════════════════════════════
# GGUF EXPORT + OLLAMA REGISTRATION
# ═══════════════════════════════════════════════════════════════════════

def export_to_gguf(model_dir: str, output_path: str,
                   quantization: str = "q4_k_m"):
    """Export a LoRA-merged model to GGUF for Ollama deployment."""
    logger.info(f"=== GGUF EXPORT ===")
    logger.info(f"Model: {model_dir} → {output_path}")

    meta_file = Path(model_dir) / "titan_training_meta.json"
    if not meta_file.exists():
        logger.error(f"No training metadata found at {meta_file}")
        return False

    meta = json.loads(meta_file.read_text())
    task_type = meta.get("task", "action")

    try:
        if task_type == "vision":
            from unsloth import FastVisionModel
            model, tokenizer = FastVisionModel.from_pretrained(
                model_name=model_dir,
                load_in_4bit=False,
            )
        else:
            from unsloth import FastLanguageModel
            model, tokenizer = FastLanguageModel.from_pretrained(
                model_name=model_dir,
                load_in_4bit=False,
            )
    except ImportError:
        logger.error("unsloth not installed")
        return False

    logger.info(f"Saving merged model as GGUF ({quantization})...")
    model.save_pretrained_gguf(
        output_path,
        tokenizer,
        quantization_method=quantization,
    )

    logger.info(f"GGUF saved to {output_path}")

    # Generate Ollama Modelfile
    model_name = "titan-agent" if task_type == "action" else "titan-screen"
    gguf_file = list(Path(output_path).glob("*.gguf"))
    if gguf_file:
        modelfile_content = f"""FROM ./{gguf_file[0].name}
SYSTEM "You are Titan AI agent controlling an Android device. Analyze the screen state and output the next action as a JSON object."
PARAMETER temperature 0.2
PARAMETER num_predict 512
PARAMETER stop "<|im_end|>"
"""
        modelfile_path = Path(output_path) / "Modelfile"
        modelfile_path.write_text(modelfile_content)
        logger.info(f"Modelfile written to {modelfile_path}")
        logger.info(f"Register with: ollama create {model_name}:7b -f {modelfile_path}")

    return True


# ═══════════════════════════════════════════════════════════════════════
# STATS
# ═══════════════════════════════════════════════════════════════════════

def show_stats(data_dir: str):
    """Show trajectory collection statistics."""
    from trajectory_logger import TrainingDataExporter
    exporter = TrainingDataExporter(trajectory_dir=data_dir)
    stats = exporter.stats()

    print("\n" + "=" * 60)
    print("TITAN TRAINING DATA STATISTICS")
    print("=" * 60)
    print(f"  Trajectory directory: {data_dir}")
    print(f"  Total trajectories:   {stats['total_trajectories']}")
    print(f"  Completed:            {stats['completed']}")
    print(f"  Failed:               {stats['failed']}")
    print(f"  Total steps:          {stats['total_steps']}")
    print(f"  Successful steps:     {stats['successful_steps']}")
    print(f"  Step success rate:    {stats['step_success_rate']:.1%}")
    print(f"  Disk usage:           {stats['disk_usage_mb']:.1f} MB")
    print(f"\n  By category:")
    for cat, count in stats.get("categories", {}).items():
        print(f"    {cat}: {count}")

    # Check training readiness
    print(f"\n  Training readiness:")
    action_ready = stats['successful_steps'] >= 100
    vision_ready = stats['completed'] >= 20
    a_steps = stats['successful_steps']
    c_count = stats['completed']
    a_label = "READY" if action_ready else f"NOT READY ({a_steps}/100)"
    v_label = "READY" if vision_ready else f"NOT READY ({c_count}/20)"
    print(f"    Action model (need 100+ steps):  {a_label}")
    print(f"    Vision model (need 20+ trajs):   {v_label}")
    print("=" * 60 + "\n")


# ═══════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Titan AI Model Training")
    parser.add_argument("--task", required=True,
                        choices=["action", "vision", "export", "stats"],
                        help="Training task type")
    parser.add_argument("--data", default="/opt/titan/data/trajectories",
                        help="Trajectory data directory")
    parser.add_argument("--output", default="",
                        help="Output directory for trained model / GGUF")
    parser.add_argument("--model", default="",
                        help="Base model name (HuggingFace) or model dir for export")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--rank", type=int, default=16, help="LoRA rank")
    parser.add_argument("--alpha", type=int, default=32, help="LoRA alpha")
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--grad-accum", type=int, default=4)
    parser.add_argument("--max-seq-len", type=int, default=2048)
    parser.add_argument("--quantization", default="q4_k_m",
                        help="GGUF quantization type for export")
    parser.add_argument("--min-success-rate", type=float, default=0.5,
                        help="Min trajectory success rate for action training")

    args = parser.parse_args()

    if args.task == "stats":
        show_stats(args.data)
        return

    if args.task == "action":
        base = args.model or "Qwen/Qwen2.5-7B-Instruct"
        out = args.output or "/opt/titan/models/titan-agent-7b-lora"
        ok = train_action_model(
            data_dir=args.data, output_dir=out, base_model=base,
            epochs=args.epochs, lr=args.lr, rank=args.rank, alpha=args.alpha,
            batch_size=args.batch_size, grad_accum=args.grad_accum,
            max_seq_len=args.max_seq_len,
        )
        sys.exit(0 if ok else 1)

    elif args.task == "vision":
        base = args.model or "Qwen/Qwen2-VL-7B-Instruct"
        out = args.output or "/opt/titan/models/titan-screen-7b-lora"
        ok = train_vision_model(
            data_dir=args.data, output_dir=out, base_model=base,
            epochs=args.epochs, lr=args.lr, rank=args.rank, alpha=args.alpha,
            batch_size=args.batch_size, grad_accum=args.grad_accum,
            max_seq_len=args.max_seq_len,
        )
        sys.exit(0 if ok else 1)

    elif args.task == "export":
        model_dir = args.model
        if not model_dir:
            logger.error("--model required for export (path to LoRA adapter dir)")
            sys.exit(1)
        out = args.output or model_dir + "-gguf"
        ok = export_to_gguf(model_dir, out, quantization=args.quantization)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
