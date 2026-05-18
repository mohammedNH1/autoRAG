"""
decoder/model.py
----------------
A small-scale Decoder-Only Transformer built from scratch with PyTorch.
Designed to serve as the LLM component inside an AutoRAG pipeline.

Architecture overview:
  Token Embedding + Positional Encoding
  → N x Transformer Decoder Blocks
      └─ Masked Multi-Head Self-Attention  (causal mask)
      └─ Feed-Forward Network
      └─ Layer Normalization + Residual connections
  → Linear projection → Vocabulary logits
"""

import math
import torch
import torch.nn as nn
import torch.nn.functional as F


# ---------------------------------------------------------------------------
# 1. Positional Encoding
# ---------------------------------------------------------------------------

class PositionalEncoding(nn.Module):
    """
    Classic sinusoidal positional encoding (Vaswani et al., 2017).
    Adds position information to token embeddings so the model knows
    the order of tokens in a sequence.
    """

    def __init__(self, d_model: int, max_seq_len: int = 512, dropout: float = 0.1):
        super().__init__()
        self.dropout = nn.Dropout(dropout)

        # Build a (max_seq_len, d_model) table of positional values
        pe = torch.zeros(max_seq_len, d_model)                        # [T, D]
        position = torch.arange(0, max_seq_len).unsqueeze(1).float()  # [T, 1]
        div_term = torch.exp(
            torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model)
        )                                                              # [D/2]

        pe[:, 0::2] = torch.sin(position * div_term)   # even dims → sin
        pe[:, 1::2] = torch.cos(position * div_term)   # odd  dims → cos

        pe = pe.unsqueeze(0)          # [1, T, D]  — batch dim for broadcasting
        self.register_buffer("pe", pe)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """x: [B, T, D]"""
        x = x + self.pe[:, : x.size(1), :]
        return self.dropout(x)


# ---------------------------------------------------------------------------
# 2. Masked Multi-Head Self-Attention
# ---------------------------------------------------------------------------

class MultiHeadSelfAttention(nn.Module):
    """
    Multi-head self-attention with a *causal mask* so that each token
    can only attend to itself and earlier tokens (decoder behaviour).
    """

    def __init__(self, d_model: int, n_heads: int, dropout: float = 0.1):
        super().__init__()
        assert d_model % n_heads == 0, "d_model must be divisible by n_heads"

        self.d_model  = d_model
        self.n_heads  = n_heads
        self.d_head   = d_model // n_heads   # dimension per head

        # Projections for Q, K, V and the final output
        self.W_q = nn.Linear(d_model, d_model, bias=False)
        self.W_k = nn.Linear(d_model, d_model, bias=False)
        self.W_v = nn.Linear(d_model, d_model, bias=False)
        self.W_o = nn.Linear(d_model, d_model, bias=False)

        self.dropout = nn.Dropout(dropout)
        self.scale   = math.sqrt(self.d_head)

    def _split_heads(self, x: torch.Tensor) -> torch.Tensor:
        """[B, T, D] → [B, H, T, d_head]"""
        B, T, D = x.shape
        x = x.view(B, T, self.n_heads, self.d_head)
        return x.transpose(1, 2)   # [B, H, T, d_head]

    def _merge_heads(self, x: torch.Tensor) -> torch.Tensor:
        """[B, H, T, d_head] → [B, T, D]"""
        B, H, T, d = x.shape
        x = x.transpose(1, 2).contiguous()
        return x.view(B, T, H * d)

    def forward(self, x: torch.Tensor, mask: torch.Tensor = None) -> torch.Tensor:
        """
        x    : [B, T, D]
        mask : [1, 1, T, T]  — upper-triangular causal mask (−inf above diagonal)
        """
        Q = self._split_heads(self.W_q(x))   # [B, H, T, d_head]
        K = self._split_heads(self.W_k(x))
        V = self._split_heads(self.W_v(x))

        # Scaled dot-product attention
        scores = torch.matmul(Q, K.transpose(-2, -1)) / self.scale  # [B, H, T, T]

        if mask is not None:
            scores = scores + mask   # add −inf to future positions

        attn_weights = F.softmax(scores, dim=-1)
        attn_weights = self.dropout(attn_weights)

        context = torch.matmul(attn_weights, V)   # [B, H, T, d_head]
        context = self._merge_heads(context)       # [B, T, D]
        return self.W_o(context)


# ---------------------------------------------------------------------------
# 3. Position-wise Feed-Forward Network
# ---------------------------------------------------------------------------

class FeedForward(nn.Module):
    """
    Two-layer MLP applied independently to each position.
    Inner dimension is typically 4× d_model (standard GPT practice).
    """

    def __init__(self, d_model: int, d_ff: int, dropout: float = 0.1):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(d_model, d_ff),
            nn.GELU(),             # smoother than ReLU; used in GPT-2/3
            nn.Dropout(dropout),
            nn.Linear(d_ff, d_model),
            nn.Dropout(dropout),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


# ---------------------------------------------------------------------------
# 4. Single Transformer Decoder Block
# ---------------------------------------------------------------------------

class DecoderBlock(nn.Module):
    """
    One layer of the decoder stack:
      x → LayerNorm → MaskedMHSA → residual
        → LayerNorm → FFN         → residual
    Pre-LN (normalise before sub-layer) is used for training stability.
    """

    def __init__(self, d_model: int, n_heads: int, d_ff: int, dropout: float = 0.1):
        super().__init__()
        self.ln1  = nn.LayerNorm(d_model)
        self.attn = MultiHeadSelfAttention(d_model, n_heads, dropout)
        self.ln2  = nn.LayerNorm(d_model)
        self.ff   = FeedForward(d_model, d_ff, dropout)

    def forward(self, x: torch.Tensor, mask: torch.Tensor = None) -> torch.Tensor:
        # Self-attention sub-layer (pre-LN + residual)
        x = x + self.attn(self.ln1(x), mask)
        # Feed-forward sub-layer (pre-LN + residual)
        x = x + self.ff(self.ln2(x))
        return x


# ---------------------------------------------------------------------------
# 5. Full Decoder-Only Language Model
# ---------------------------------------------------------------------------

class DecoderOnlyLM(nn.Module):
    """
    GPT-style decoder-only language model.

    Parameters
    ----------
    vocab_size   : number of tokens in the vocabulary
    d_model      : embedding / hidden dimension  (e.g. 256)
    n_heads      : number of attention heads     (e.g. 8)
    n_layers     : number of stacked DecoderBlocks (e.g. 4)
    d_ff         : inner dimension of FFN        (e.g. 1024 = 4 × d_model)
    max_seq_len  : maximum context window length (e.g. 512)
    dropout      : dropout probability           (e.g. 0.1)
    """

    def __init__(
        self,
        vocab_size:  int,
        d_model:     int = 256,
        n_heads:     int = 8,
        n_layers:    int = 4,
        d_ff:        int = 1024,
        max_seq_len: int = 512,
        dropout:     float = 0.1,
    ):
        super().__init__()
        self.d_model     = d_model
        self.max_seq_len = max_seq_len

        # --- Embedding layers ---
        self.token_emb = nn.Embedding(vocab_size, d_model)
        self.pos_enc   = PositionalEncoding(d_model, max_seq_len, dropout)

        # --- Stacked decoder blocks ---
        self.blocks = nn.ModuleList(
            [DecoderBlock(d_model, n_heads, d_ff, dropout) for _ in range(n_layers)]
        )

        # --- Final layer norm + projection to vocabulary ---
        self.ln_f  = nn.LayerNorm(d_model)
        self.head  = nn.Linear(d_model, vocab_size, bias=False)

        # Weight tying: share weights between token embedding and output projection
        # (standard practice from "Press & Wolf, 2017"; reduces parameters)
        self.head.weight = self.token_emb.weight

        self._init_weights()

    # ------------------------------------------------------------------
    # Weight initialisation (GPT-2 style)
    # ------------------------------------------------------------------

    def _init_weights(self):
        for module in self.modules():
            if isinstance(module, nn.Linear):
                nn.init.normal_(module.weight, mean=0.0, std=0.02)
                if module.bias is not None:
                    nn.init.zeros_(module.bias)
            elif isinstance(module, nn.Embedding):
                nn.init.normal_(module.weight, mean=0.0, std=0.02)
            elif isinstance(module, nn.LayerNorm):
                nn.init.ones_(module.weight)
                nn.init.zeros_(module.bias)

    # ------------------------------------------------------------------
    # Causal mask builder
    # ------------------------------------------------------------------

    def _causal_mask(self, seq_len: int, device: torch.device) -> torch.Tensor:
        """
        Upper-triangular mask filled with −∞ so future tokens are invisible.
        Shape: [1, 1, T, T]
        """
        mask = torch.triu(
            torch.full((seq_len, seq_len), float("-inf"), device=device),
            diagonal=1,
        )
        return mask.unsqueeze(0).unsqueeze(0)   # [1, 1, T, T]

    # ------------------------------------------------------------------
    # Forward pass
    # ------------------------------------------------------------------

    def forward(self, input_ids: torch.Tensor) -> torch.Tensor:
        """
        Parameters
        ----------
        input_ids : LongTensor of shape [B, T]
                    Token indices for a batch of sequences.

        Returns
        -------
        logits : FloatTensor of shape [B, T, vocab_size]
                 Raw (unnormalised) scores over the vocabulary at each position.
        """
        B, T = input_ids.shape
        assert T <= self.max_seq_len, (
            f"Sequence length {T} exceeds max_seq_len {self.max_seq_len}."
        )

        # Token embeddings scaled by √d_model (standard practice)
        x = self.token_emb(input_ids) * math.sqrt(self.d_model)  # [B, T, D]
        x = self.pos_enc(x)                                        # [B, T, D]

        # Build causal mask once and reuse across all layers
        mask = self._causal_mask(T, input_ids.device)

        for block in self.blocks:
            x = block(x, mask)

        x = self.ln_f(x)           # final layer norm
        logits = self.head(x)      # [B, T, vocab_size]
        return logits

    # ------------------------------------------------------------------
    # Autoregressive generation (greedy / temperature sampling)
    # ------------------------------------------------------------------

    @torch.no_grad()
    def generate(
        self,
        input_ids:          torch.Tensor,
        max_new_tokens:     int   = 200,
        temperature:        float = 1.0,
        top_k:              int   = 50,
        stop_token:         int   = None,
        repetition_penalty: float = 2.0,
    ) -> torch.Tensor:
        """
        Autoregressively generate tokens given a prompt.

        Parameters
        ----------
        input_ids           : [1, T] — prompt token ids (batch size must be 1)
        max_new_tokens      : how many tokens to generate
        temperature         : >1 → more random, <1 → more deterministic
        top_k               : sample from the top-k most likely tokens (0 = greedy)
        stop_token          : stop generation when this token id is produced
        repetition_penalty  : >1.0 penalizes tokens that already appeared (1.0 = off)
                              1.3 is a good default — strong enough to stop loops

        Returns
        -------
        generated_ids : [1, T + max_new_tokens]
        """
        self.eval()
        for _ in range(max_new_tokens):
            # Crop context if it exceeds max_seq_len
            ctx = input_ids[:, -self.max_seq_len :]

            logits = self.forward(ctx)           # [1, T, vocab_size]
            logits = logits[:, -1, :]            # last position → [1, vocab_size]

            # Repetition penalty — divide logits of already-seen tokens
            # by the penalty factor (>1 makes them less likely)
            if repetition_penalty != 1.0:
                for token_id in set(input_ids[0].tolist()):
                    if logits[0, token_id] < 0:
                        logits[0, token_id] *= repetition_penalty
                    else:
                        logits[0, token_id] /= repetition_penalty

            # Apply temperature
            logits = logits / max(temperature, 1e-8)

            # Top-k filtering
            if top_k > 0:
                values, _ = torch.topk(logits, min(top_k, logits.size(-1)))
                min_val    = values[:, -1].unsqueeze(-1)
                logits     = logits.masked_fill(logits < min_val, float("-inf"))

            probs     = F.softmax(logits, dim=-1)           # [1, vocab_size]
            next_tok  = torch.multinomial(probs, num_samples=1)  # [1, 1]
            input_ids = torch.cat([input_ids, next_tok], dim=1)

            # Stop at stop token
            if stop_token is not None and next_tok.item() == stop_token:
                break

        return input_ids

    # ------------------------------------------------------------------
    # Utility: count parameters
    # ------------------------------------------------------------------

    def count_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters() if p.requires_grad)