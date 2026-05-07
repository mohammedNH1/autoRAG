"""
decoder/train.py
-----------------
Standalone training script for the decoder LLM.
Supports both pre-training from scratch AND fine-tuning from a checkpoint.

Optimized for low-VRAM GPUs (e.g. RTX 3050 Ti 4GB) via:
  • Gradient accumulation  — simulates large batches with small ones
  • Mixed precision (fp16) — halves VRAM usage
  • num_workers=2          — faster data loading

--- Pre-training (run 1) ---
    python3 -m decoder.train \
        --data_path  data/corpus_small.txt \
        --output_dir checkpoints/pretrained \
        --epochs     10 \
        --batch_size 8 \
        --grad_accum 8 \
        --fp16

--- Fine-tuning (run 2) ---
    python3 -m decoder.train \
        --data_path   data/finetune.txt \
        --output_dir  checkpoints/finetuned \
        --resume_from checkpoints/pretrained \
        --epochs      3 \
        --lr          1e-4 \
        --batch_size  8 \
        --grad_accum  8 \
        --fp16

Effective batch size = --batch_size x --grad_accum
  e.g. batch_size=8, grad_accum=8 → effective batch = 64

When --resume_from is given:
  • Model weights + architecture loaded from checkpoint
  • Architecture flags (--d_model, --n_layers, etc.) are IGNORED
  • Only --lr, --epochs, --batch_size, --grad_accum, --fp16 can differ
"""

import argparse
import os
import time
import math

import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

from .model     import DecoderOnlyLM
from .tokenizer import TiktokenWrapper


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------

class TextDataset(Dataset):
    """
    Sliding-window token dataset.
    Each sample is (input_ids[:-1], input_ids[1:]) — next-token prediction.
    Works for both raw text (pre-training) and Q&A text (fine-tuning).
    """

    def __init__(self, token_ids: list, seq_len: int):
        self.ids     = token_ids
        self.seq_len = seq_len

    def __len__(self):
        return max(0, len(self.ids) - self.seq_len)

    def __getitem__(self, idx):
        chunk = self.ids[idx : idx + self.seq_len + 1]
        x = torch.tensor(chunk[:-1], dtype=torch.long)
        y = torch.tensor(chunk[1:],  dtype=torch.long)
        return x, y


# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------

def load_checkpoint(checkpoint_dir: str, device: str):
    """
    Load model weights + config from a checkpoint directory.
    Returns (model, model_config).
    """
    model_path  = os.path.join(checkpoint_dir, "model.pt")
    config_path = os.path.join(checkpoint_dir, "config.pt")

    if not os.path.exists(model_path):
        raise FileNotFoundError(f"No model.pt found in {checkpoint_dir}")
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"No config.pt found in {checkpoint_dir}")

    model_config = torch.load(config_path, map_location="cpu")
    model        = DecoderOnlyLM(**model_config)
    state_dict   = torch.load(model_path, map_location="cpu")
    model.load_state_dict(state_dict)
    model        = model.to(device)

    print(f"[train] Loaded checkpoint      : {checkpoint_dir}")
    print(f"[train] Architecture           : d_model={model_config['d_model']}, "
          f"n_layers={model_config['n_layers']}, n_heads={model_config['n_heads']}")
    return model, model_config


def save_checkpoint(model, model_config: dict, tokenizer, output_dir: str):
    """Save model weights + config + tokenizer to output_dir."""
    os.makedirs(output_dir, exist_ok=True)
    torch.save(model.state_dict(), os.path.join(output_dir, "model.pt"))
    torch.save(model_config,       os.path.join(output_dir, "config.pt"))
    tokenizer.save(os.path.join(output_dir, "tokenizer.json"))
    print(f"[train] Checkpoint saved       : {output_dir}")


# ---------------------------------------------------------------------------
# VRAM estimator
# ---------------------------------------------------------------------------

def estimate_vram_mb(vocab_size, d_model, n_layers, seq_len,
                     batch_size, fp16=False) -> float:
    """Rough VRAM estimate in MB before training starts."""
    bpp          = 2 if fp16 else 4
    embed_params = vocab_size * d_model
    layer_params = n_layers * (4 * d_model * d_model + 2 * d_model * d_model * 4 + 4 * d_model)
    total_params = embed_params + layer_params
    param_bytes  = total_params * bpp
    grad_bytes   = total_params * bpp
    adam_bytes   = total_params * 4 * 2        # Adam m+v always fp32
    act_bytes    = batch_size * seq_len * d_model * n_layers * bpp
    return (param_bytes + grad_bytes + adam_bytes + act_bytes) / (1024 ** 2)


# ---------------------------------------------------------------------------
# Training loop
# ---------------------------------------------------------------------------

def train(args):
    device   = "cuda" if torch.cuda.is_available() else "cpu"
    use_fp16 = args.fp16 and device == "cuda"

    # --- Print run summary ---
    print(f"[train] Device          : {device}")
    if device == "cuda":
        vram_total = torch.cuda.get_device_properties(0).total_memory / (1024 ** 2)
        print(f"[train] GPU             : {torch.cuda.get_device_name(0)}")
        print(f"[train] VRAM total      : {vram_total:.0f} MB")
    print(f"[train] Mixed precision : {'ON (fp16)' if use_fp16 else 'OFF (fp32)'}")

    is_finetuning  = args.resume_from is not None
    effective_batch = args.batch_size * args.grad_accum
    print(f"[train] Mode            : {'FINE-TUNING from ' + args.resume_from if is_finetuning else 'PRE-TRAINING from scratch'}")
    print(f"[train] Effective batch : {args.batch_size} x {args.grad_accum} accum = {effective_batch}")

    # ------------------------------------------------------------------
    # 1. Tokenizer
    # When fine-tuning, load the tokenizer FROM the checkpoint so the
    # encoding matches the model vocab (e.g. r50k_base for GPT-2).
    # When pre-training from scratch, use the default cl100k_base.
    # ------------------------------------------------------------------
    if is_finetuning:
        tokenizer_path = os.path.join(args.resume_from, "tokenizer.json")
        if os.path.exists(tokenizer_path):
            tokenizer = TiktokenWrapper.load(tokenizer_path)
            print(f"[train] Tokenizer       : loaded from checkpoint ({tokenizer.encoding_name})")
        else:
            tokenizer = TiktokenWrapper()
            print(f"[train] Tokenizer       : default ({tokenizer.encoding_name})")
    else:
        tokenizer = TiktokenWrapper()
        print(f"[train] Tokenizer       : default ({tokenizer.encoding_name})")
    print(f"[train] Vocab size      : {tokenizer.vocab_size}")

    # ------------------------------------------------------------------
    # 2. Load corpus
    # ------------------------------------------------------------------
    with open(args.data_path, encoding="utf-8") as f:
        text = f.read()
    print(f"[train] Corpus          : {args.data_path} ({len(text):,} chars)")

    ids = tokenizer.encode(text, add_special_tokens=False)
    print(f"[train] Tokens          : {len(ids):,}")

    # ------------------------------------------------------------------
    # 3. Dataset / DataLoader
    # ------------------------------------------------------------------
    dataset = TextDataset(ids, seq_len=args.seq_len)
    if len(dataset) == 0:
        raise ValueError(
            f"Dataset is empty — corpus too short for seq_len={args.seq_len}. "
            f"Use a longer corpus or reduce --seq_len."
        )

    dataloader = DataLoader(
        dataset,
        batch_size  = args.batch_size,
        shuffle     = True,
        drop_last   = True,
        num_workers = 2,        # parallel data loading — faster than 0
        pin_memory  = (device == "cuda"),  # faster CPU→GPU transfer
    )

    steps_per_epoch = math.ceil(len(dataloader) / args.grad_accum)
    total_steps     = steps_per_epoch * args.epochs
    print(f"[train] Batches/epoch   : {len(dataloader):,}")
    print(f"[train] Steps/epoch     : {steps_per_epoch:,}")
    print(f"[train] Total steps     : {total_steps:,}  ({args.epochs} epochs)")

    # ------------------------------------------------------------------
    # 4. Build or load model
    # ------------------------------------------------------------------
    if is_finetuning:
        model, model_config = load_checkpoint(args.resume_from, device)
        if args.dropout != 0.1:
            model_config["dropout"] = args.dropout
    else:
        model_config = {
            "vocab_size":  tokenizer.vocab_size,
            "d_model":     args.d_model,
            "n_heads":     args.n_heads,
            "n_layers":    args.n_layers,
            "d_ff":        args.d_ff,
            "max_seq_len": args.seq_len,
            "dropout":     args.dropout,
        }
        model = DecoderOnlyLM(**model_config).to(device)

    print(f"[train] Parameters      : {model.count_parameters():,}")

    # VRAM warning
    if device == "cuda":
        est_mb = estimate_vram_mb(
            vocab_size = model_config["vocab_size"],
            d_model    = model_config["d_model"],
            n_layers   = model_config["n_layers"],
            seq_len    = args.seq_len,
            batch_size = args.batch_size,
            fp16       = use_fp16,
        )
        print(f"[train] VRAM estimate   : ~{est_mb:.0f} MB / {vram_total:.0f} MB")
        if est_mb > vram_total * 0.9:
            print(f"[train] ⚠️  WARNING: may run out of VRAM.")
            print(f"[train]    Try: --batch_size 4 --grad_accum 16 --fp16")

    # ------------------------------------------------------------------
    # 5. Optimizer + scheduler + fp16 scaler
    # ------------------------------------------------------------------
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr           = args.lr,
        weight_decay = 0.01,
    )

    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer,
        T_max   = total_steps,
        eta_min = args.lr * 0.1,
    )

    scaler    = torch.amp.GradScaler('cuda', enabled=use_fp16)
    criterion = nn.CrossEntropyLoss(ignore_index=tokenizer.pad_id)

    # ------------------------------------------------------------------
    # 6. Training loop with gradient accumulation + fp16
    # ------------------------------------------------------------------
    model.train()
    global_step = 0
    best_loss   = float("inf")

    print(f"\n[train] Starting...\n")

    for epoch in range(1, args.epochs + 1):
        epoch_loss = 0.0
        t0         = time.time()
        optimizer.zero_grad()

        for batch_idx, (x, y) in enumerate(dataloader):
            x, y = x.to(device, non_blocking=True), y.to(device, non_blocking=True)

            # Forward — autocast for fp16
            with torch.amp.autocast('cuda', enabled=use_fp16):
                logits = model(x)
                loss   = criterion(
                    logits.reshape(-1, tokenizer.vocab_size),
                    y.reshape(-1),
                )
                loss_scaled = loss / args.grad_accum

            # Backward
            scaler.scale(loss_scaled).backward()
            epoch_loss += loss.item()

            is_last_batch = (batch_idx + 1) == len(dataloader)
            is_accum_step = (batch_idx + 1) % args.grad_accum == 0

            if is_accum_step or is_last_batch:
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                # Save scale before step — if scaler skips the optimizer
                # step (inf/nan grads), we should not step the scheduler
                scale_before = scaler.get_scale()
                scaler.step(optimizer)
                scaler.update()
                optimizer.zero_grad()
                # Only step scheduler if optimizer actually updated
                if scaler.get_scale() == scale_before:
                    scheduler.step()
                global_step += 1

                # Mid-epoch checkpoint save
                if args.save_every > 0 and global_step % args.save_every == 0:
                    save_checkpoint(model, model_config, tokenizer,
                                    os.path.join(args.output_dir, f"step_{global_step}"))

                if global_step % args.log_every == 0:
                    ppl      = math.exp(min(loss.item(), 20))
                    vram_msg = ""
                    if device == "cuda":
                        used     = torch.cuda.memory_allocated() / (1024 ** 2)
                        vram_msg = f" | vram {used:.0f}MB"
                    pct = global_step / total_steps * 100
                    print(
                        f"  step {global_step:>6}/{total_steps} ({pct:.1f}%) | "
                        f"loss {loss.item():.4f} | ppl {ppl:.1f} | "
                        f"lr {scheduler.get_last_lr()[0]:.2e}{vram_msg}"
                    )

        avg_loss = epoch_loss / len(dataloader)
        elapsed  = time.time() - t0
        ppl      = math.exp(min(avg_loss, 20))
        remaining_epochs = args.epochs - epoch
        eta_min  = (elapsed * remaining_epochs) / 60

        print(
            f"Epoch {epoch}/{args.epochs} | "
            f"avg loss {avg_loss:.4f} | ppl {ppl:.1f} | "
            f"time {elapsed:.1f}s | ETA ~{eta_min:.0f} min"
        )

        if avg_loss < best_loss:
            best_loss = avg_loss
            save_checkpoint(model, model_config, tokenizer,
                            os.path.join(args.output_dir, "best"))

    # ------------------------------------------------------------------
    # 7. Save final checkpoint
    # ------------------------------------------------------------------
    save_checkpoint(model, model_config, tokenizer, args.output_dir)

    print(f"\n[train] Done.")
    print(f"  Final checkpoint : {args.output_dir}")
    print(f"  Best checkpoint  : {os.path.join(args.output_dir, 'best')}")
    print(f"  Best loss        : {best_loss:.4f}")
    print()

    if is_finetuning:
        print("Next step — add to settings.py:")
        print(f"  DECODER_CHECKPOINT = '{args.output_dir}'")
    else:
        print("Next step — fine-tune with:")
        print(
            f"  python3 -m decoder.train \\\n"
            f"      --data_path   data/finetune.txt \\\n"
            f"      --output_dir  checkpoints/finetuned \\\n"
            f"      --resume_from {args.output_dir} \\\n"
            f"      --epochs 3 --lr 1e-4 \\\n"
            f"      --batch_size {args.batch_size} --grad_accum {args.grad_accum}"
            + (" --fp16" if use_fp16 else "")
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description="Train or fine-tune the decoder LLM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
RTX 3050 Ti (4GB) recommended settings:
  python3 -m decoder.train --data_path data/corpus_small.txt \\
      --output_dir checkpoints/pretrained \\
      --batch_size 8 --grad_accum 8 --fp16

  Effective batch = 8 x 8 = 64  (same quality as batch_size=64, 4x less VRAM)
        """,
    )

    # --- Data ---
    p.add_argument("--data_path",   required=True,
                   help="Path to .txt corpus (pre-training) or Q&A file (fine-tuning)")
    p.add_argument("--output_dir",  default="checkpoints/decoder_v1",
                   help="Where to save the checkpoint")

    # --- Resume ---
    p.add_argument("--resume_from", default=None,
                   help="Checkpoint dir to load weights from (fine-tuning mode). "
                        "Architecture args are IGNORED when set.")

    # --- Hyperparams ---
    p.add_argument("--epochs",      type=int,   default=10)
    p.add_argument("--batch_size",  type=int,   default=8,
                   help="Per-step batch size. Keep 4-8 for 4GB GPU.")
    p.add_argument("--grad_accum",  type=int,   default=8,
                   help="Gradient accumulation steps. Effective batch = batch_size x grad_accum.")
    p.add_argument("--seq_len",     type=int,   default=128)
    p.add_argument("--lr",          type=float, default=3e-4,
                   help="3e-4 for pre-training, 1e-4 for fine-tuning.")
    p.add_argument("--dropout",     type=float, default=0.1)
    p.add_argument("--fp16",        action="store_true",
                   help="Mixed precision training. Halves VRAM. Recommended for 4GB GPU.")
    p.add_argument("--save_every",  type=int,   default=0,
                   help="Save checkpoint every N steps (0 = disabled). Useful for long runs.")
    p.add_argument("--log_every",   type=int,   default=50,
                   help="Print loss every N optimizer steps.")

    # --- Architecture (pre-training only) ---
    p.add_argument("--d_model",     type=int,   default=256)
    p.add_argument("--n_heads",     type=int,   default=8)
    p.add_argument("--n_layers",    type=int,   default=4)
    p.add_argument("--d_ff",        type=int,   default=1024)

    return p.parse_args()


if __name__ == "__main__":
    train(parse_args())