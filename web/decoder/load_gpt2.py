"""
decoder/load_gpt2.py
---------------------
Downloads GPT-2 Small weights from HuggingFace and maps them onto
your DecoderOnlyLM architecture — saving a checkpoint in the exact
same format that train.py and RAGInference expect.

After running this script, fine-tune normally:

    python3 -m decoder.train \
        --data_path   data/finetune_small.txt \
        --output_dir  checkpoints/gpt2_finetuned \
        --resume_from checkpoints/gpt2_pretrained \
        --epochs      3 \
        --lr          1e-4 \
        --batch_size  8 \
        --grad_accum  8 \
        --fp16

Install requirements first:
    pip3 install transformers --break-system-packages

Run from your Django project root:
    python3 -m decoder.load_gpt2

Architecture mapping (GPT-2 Small → your DecoderOnlyLM)
---------------------------------------------------------
GPT-2 uses the EXACT same architecture you built:
  • Token embedding        : wte.weight         → token_emb.weight
  • Positional embedding   : wpe.weight         → pos_enc.pe  (*)
  • Attention Q/K/V        : attn.c_attn.weight → W_q, W_k, W_v
  • Attention output       : attn.c_proj.weight → W_o
  • FFN layer 1            : mlp.c_fc.weight    → ff.net[0]
  • FFN layer 2            : mlp.c_proj.weight  → ff.net[3]
  • LayerNorm 1            : ln_1               → ln1
  • LayerNorm 2            : ln_2               → ln2
  • Final LayerNorm        : ln_f               → ln_f

(*) GPT-2 uses learned positional embeddings while your model uses
    sinusoidal. We keep your sinusoidal PE and only load the rest.
    This is fine — sinusoidal PE is equally effective.

GPT-2 Small dimensions:
  vocab_size = 50257
  d_model    = 768
  n_heads    = 12
  n_layers   = 12
  d_ff       = 3072  (4 × d_model)
  max_seq_len= 1024
"""

import os
import torch

# ---------------------------------------------------------------------------
# Mapping helpers
# ---------------------------------------------------------------------------

def load_gpt2_into_decoder(
    output_dir: str = "checkpoints/gpt2_pretrained",
    max_seq_len: int = 512,
):
    """
    Download GPT-2 Small and save it as a DecoderOnlyLM checkpoint.

    Parameters
    ----------
    output_dir  : where to save the converted checkpoint
    max_seq_len : context length (512 is safe for 4GB VRAM; GPT-2 supports 1024)
    """
    try:
        from transformers import GPT2Model, GPT2Config
    except ImportError:
        raise ImportError(
            "transformers not installed.\n"
            "Run: pip3 install transformers --break-system-packages"
        )

    # Use relative imports when run as a module
    from .model     import DecoderOnlyLM
    from .tokenizer import TiktokenWrapper

    print("[load_gpt2] Downloading GPT-2 Small from HuggingFace (~500MB)...")
    gpt2 = GPT2Model.from_pretrained("gpt2")   # 'gpt2' = GPT-2 Small (117M params)
    gpt2_sd = gpt2.state_dict()
    print("[load_gpt2] Download complete.")

    # ------------------------------------------------------------------
    # GPT-2 Small config
    # ------------------------------------------------------------------
    GPT2_VOCAB   = 50257
    GPT2_D_MODEL = 768
    GPT2_HEADS   = 12
    GPT2_LAYERS  = 12
    GPT2_D_FF    = 3072

    model_config = {
        "vocab_size":  GPT2_VOCAB,
        "d_model":     GPT2_D_MODEL,
        "n_heads":     GPT2_HEADS,
        "n_layers":    GPT2_LAYERS,
        "d_ff":        GPT2_D_FF,
        "max_seq_len": max_seq_len,
        "dropout":     0.1,
    }

    print(f"[load_gpt2] Building DecoderOnlyLM with GPT-2 dimensions...")
    model = DecoderOnlyLM(**model_config)
    our_sd = model.state_dict()

    # ------------------------------------------------------------------
    # Weight mapping
    # GPT-2 key             →  Your key
    # ------------------------------------------------------------------
    # GPT-2 stores Q, K, V concatenated in one matrix c_attn [D, 3D]
    # We need to split it into W_q, W_k, W_v each [D, D]
    # GPT-2 uses Conv1D (transposed vs nn.Linear) so we transpose weights

    copied   = []
    skipped  = []

    # 1. Token embedding
    our_sd["token_emb.weight"].copy_(gpt2_sd["wte.weight"])
    copied.append("token_emb.weight ← wte.weight")

    # 2. Sinusoidal PE: keep yours (don't load GPT-2's learned PE)
    skipped.append("pos_enc.pe  ← KEPT sinusoidal (not loaded from GPT-2)")

    # 3. Transformer blocks
    for i in range(GPT2_LAYERS):
        gpt_pfx = f"h.{i}"
        our_pfx = f"blocks.{i}"

        # --- LayerNorm 1 ---
        our_sd[f"{our_pfx}.ln1.weight"].copy_(gpt2_sd[f"{gpt_pfx}.ln_1.weight"])
        our_sd[f"{our_pfx}.ln1.bias"  ].copy_(gpt2_sd[f"{gpt_pfx}.ln_1.bias"  ])
        copied.append(f"blocks.{i}.ln1 ← h.{i}.ln_1")

        # --- Attention Q, K, V (split from c_attn) ---
        # GPT-2 c_attn weight shape: [3*D, D]  (Conv1D → transposed from [D, 3D])
        c_attn_w = gpt2_sd[f"{gpt_pfx}.attn.c_attn.weight"]  # [D, 3D]
        c_attn_b = gpt2_sd[f"{gpt_pfx}.attn.c_attn.bias"  ]  # [3D]

        W_q_gpt, W_k_gpt, W_v_gpt = c_attn_w.split(GPT2_D_MODEL, dim=1)  # each [D, D]
        b_q_gpt, b_k_gpt, b_v_gpt = c_attn_b.split(GPT2_D_MODEL, dim=0)  # each [D]

        # Your W_q/k/v are nn.Linear(bias=False) so weight shape is [D, D]
        # GPT-2 Conv1D weight is [D, D] — same shape, just transpose
        our_sd[f"{our_pfx}.attn.W_q.weight"].copy_(W_q_gpt.T)
        our_sd[f"{our_pfx}.attn.W_k.weight"].copy_(W_k_gpt.T)
        our_sd[f"{our_pfx}.attn.W_v.weight"].copy_(W_v_gpt.T)
        copied.append(f"blocks.{i}.attn.W_q/k/v ← h.{i}.attn.c_attn (split)")

        # --- Attention output projection ---
        c_proj_w = gpt2_sd[f"{gpt_pfx}.attn.c_proj.weight"]  # [D, D]
        our_sd[f"{our_pfx}.attn.W_o.weight"].copy_(c_proj_w.T)
        copied.append(f"blocks.{i}.attn.W_o ← h.{i}.attn.c_proj")

        # --- LayerNorm 2 ---
        our_sd[f"{our_pfx}.ln2.weight"].copy_(gpt2_sd[f"{gpt_pfx}.ln_2.weight"])
        our_sd[f"{our_pfx}.ln2.bias"  ].copy_(gpt2_sd[f"{gpt_pfx}.ln_2.bias"  ])
        copied.append(f"blocks.{i}.ln2 ← h.{i}.ln_2")

        # --- FFN layer 1 (c_fc) ---
        fc_w = gpt2_sd[f"{gpt_pfx}.mlp.c_fc.weight"]    # [D, 4D]
        fc_b = gpt2_sd[f"{gpt_pfx}.mlp.c_fc.bias"  ]    # [4D]
        our_sd[f"{our_pfx}.ff.net.0.weight"].copy_(fc_w.T)
        our_sd[f"{our_pfx}.ff.net.0.bias"  ].copy_(fc_b)
        copied.append(f"blocks.{i}.ff.net.0 ← h.{i}.mlp.c_fc")

        # --- FFN layer 2 (c_proj) ---
        cp_w = gpt2_sd[f"{gpt_pfx}.mlp.c_proj.weight"]  # [4D, D]
        cp_b = gpt2_sd[f"{gpt_pfx}.mlp.c_proj.bias"  ]  # [D]
        our_sd[f"{our_pfx}.ff.net.3.weight"].copy_(cp_w.T)
        our_sd[f"{our_pfx}.ff.net.3.bias"  ].copy_(cp_b)
        copied.append(f"blocks.{i}.ff.net.3 ← h.{i}.mlp.c_proj")

    # 4. Final LayerNorm
    our_sd["ln_f.weight"].copy_(gpt2_sd["ln_f.weight"])
    our_sd["ln_f.bias"  ].copy_(gpt2_sd["ln_f.bias"  ])
    copied.append("ln_f ← ln_f")

    # 5. Load state dict into model
    # head.weight is tied to token_emb.weight — loading token_emb covers both
    model.load_state_dict(our_sd)

    # ------------------------------------------------------------------
    # Verify: run a forward pass to confirm no shape errors
    # ------------------------------------------------------------------
    print("[load_gpt2] Verifying forward pass...")
    model.eval()
    with torch.no_grad():
        dummy = torch.randint(0, GPT2_VOCAB, (1, 16))
        logits = model(dummy)
        assert logits.shape == (1, 16, GPT2_VOCAB), f"Unexpected shape: {logits.shape}"
    print(f"[load_gpt2] Forward pass OK — logits shape: {logits.shape}")

    # ------------------------------------------------------------------
    # Save checkpoint (same format as train.py)
    # ------------------------------------------------------------------
    os.makedirs(output_dir, exist_ok=True)
    torch.save(model.state_dict(), os.path.join(output_dir, "model.pt"))
    torch.save(model_config,       os.path.join(output_dir, "config.pt"))

    # Save tokenizer — GPT-2 uses r50k_base
    tokenizer = TiktokenWrapper(encoding_name="r50k_base")
    tokenizer.save(os.path.join(output_dir, "tokenizer.json"))

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print(f"\n[load_gpt2] Weights copied ({len(copied)} mappings):")
    for c in copied[:5]:
        print(f"  ✓ {c}")
    print(f"  ... and {len(copied) - 5} more layer mappings")
    print(f"\n[load_gpt2] Skipped (kept yours):")
    for s in skipped:
        print(f"  ~ {s}")

    print(f"\n[load_gpt2] Checkpoint saved to: {output_dir}")
    print(f"  model.pt       — {model.count_parameters():,} parameters")
    print(f"  config.pt      — GPT-2 Small dimensions")
    print(f"  tokenizer.json — r50k_base (GPT-2 vocab, 50,257 tokens)")

    print(f"""
[load_gpt2] Next step — fine-tune:

    python3 -m decoder.train \\
        --data_path   data/finetune_small.txt \\
        --output_dir  checkpoints/gpt2_finetuned \\
        --resume_from {output_dir} \\
        --epochs      3 \\
        --lr          1e-4 \\
        --batch_size  4 \\
        --grad_accum  16 \\
        --seq_len     256 \\
        --fp16
""")

    return model, model_config, tokenizer


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Convert GPT-2 weights to DecoderOnlyLM format")
    p.add_argument("--output_dir",  default="checkpoints/gpt2_pretrained",
                   help="Where to save the converted checkpoint")
    p.add_argument("--max_seq_len", type=int, default=512,
                   help="Context length (512 recommended for 4GB VRAM)")
    args = p.parse_args()
    load_gpt2_into_decoder(output_dir=args.output_dir, max_seq_len=args.max_seq_len)