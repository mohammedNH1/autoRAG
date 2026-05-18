"""
decoder/inference.py
---------------------
RAGInference — the bridge between the RAG pipeline and the decoder LLM.

Usage in your pipeline
-----------------------
    from decoder.inference import RAGInference

    engine = RAGInference.get_instance()

    llm_response = engine.generate_from_prompt(
        prompt      = prompt,
        temperature = temperature,
        top_p       = top_p,
        top_k       = top_k,
    )
"""

import os
import logging
import torch

from .model     import DecoderOnlyLM
from .tokenizer import TiktokenWrapper

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "vocab_size":  100_277,
    "d_model":     256,
    "n_heads":     8,
    "n_layers":    4,
    "d_ff":        1024,
    "max_seq_len": 512,
    "dropout":     0.0,
}

# Sequences that signal the model has started a new Q&A block
STOP_SEQUENCES = [
    "\nAnswer the following",
    "\nContext:",
    "\nQuestion:",
    "\n\nAnswer the",
    "\n\nContext",
    "\n\nQuestion",
]

# Repetition thresholds (used in generate_from_prompt)
MAX_SINGLE_REPEAT = 3   # stop if token X appears 3 times in a row
MAX_BIGRAM_REPEAT  = 3   # stop if pattern AB appears 3 times in a row


class RAGInference:
    """
    High-level wrapper for the decoder LLM inside the AutoRAG system.
    """

    _instance: "RAGInference" = None

    def __init__(
        self,
        model:     DecoderOnlyLM,
        tokenizer: TiktokenWrapper,
        device:    str = "cpu",
    ):
        self.model     = model.to(device)
        self.tokenizer = tokenizer
        self.device    = device
        self.model.eval()

    # ------------------------------------------------------------------
    # Singleton
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(
        cls,
        checkpoint_path: str = None,
        device: str = None,
    ) -> "RAGInference":
        if cls._instance is None:
            if checkpoint_path and os.path.isdir(checkpoint_path):
                logger.info(f"[decoder] Loading from checkpoint: {checkpoint_path}")
                cls._instance = cls.from_pretrained(checkpoint_path, device)
            else:
                logger.info("[decoder] No checkpoint — using untrained model")
                cls._instance = cls.from_scratch(device=device)
            logger.info(f"[decoder] Ready — {cls._instance.model_info()}")
        return cls._instance

    # ------------------------------------------------------------------
    # Factories
    # ------------------------------------------------------------------

    @classmethod
    def from_pretrained(
        cls,
        checkpoint_path: str,
        device: str = None,
    ) -> "RAGInference":
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"

        model_path     = os.path.join(checkpoint_path, "model.pt")
        config_path    = os.path.join(checkpoint_path, "config.pt")
        tokenizer_path = os.path.join(checkpoint_path, "tokenizer.json")

        config    = torch.load(config_path,  map_location="cpu", weights_only=False)
        tokenizer = TiktokenWrapper.load(tokenizer_path)
        config["vocab_size"] = tokenizer.vocab_size

        model = DecoderOnlyLM(**config)
        model.load_state_dict(
            torch.load(model_path, map_location="cpu", weights_only=False)
        )

        cls._instance = cls(model=model, tokenizer=tokenizer, device=device)
        return cls._instance

    @classmethod
    def from_scratch(
        cls,
        device: str = None,
        **model_kwargs,
    ) -> "RAGInference":
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"

        cfg           = {**DEFAULT_CONFIG, **model_kwargs}
        model         = DecoderOnlyLM(**cfg)
        tokenizer     = TiktokenWrapper()
        cls._instance = cls(model=model, tokenizer=tokenizer, device=device)
        return cls._instance

    # ------------------------------------------------------------------
    # Main generation method
    # ------------------------------------------------------------------

    def generate_from_prompt(
        self,
        prompt:         str,
        max_new_tokens: int   = 150,
        temperature:    float = 0.4,
        top_p:          float = 0.9,
        top_k:          int   = 10,
    ) -> str:
        ids     = self.tokenizer.encode(prompt, add_special_tokens=False)
        input_t = torch.tensor([ids], dtype=torch.long, device=self.device)

        # Truncate prompt if too long
        max_ctx = self.model.max_seq_len - max_new_tokens
        if input_t.shape[1] > max_ctx:
            logger.warning(
                f"[decoder] Prompt truncated from {input_t.shape[1]} to {max_ctx} tokens"
            )
            input_t = input_t[:, -max_ctx:]
            ids     = ids[-max_ctx:]

        # Stop on newline token
        try:
            nl_ids   = self.tokenizer.encode("\n", add_special_tokens=False)
            stop_tok = nl_ids[0] if nl_ids else None
        except Exception:
            stop_tok = None

        output_t = self.model.generate(
            input_ids           = input_t,
            max_new_tokens      = max_new_tokens,
            temperature         = temperature,
            top_k               = top_k,
            stop_token          = stop_tok,
            repetition_penalty  = 2.0,  # strong penalty
        )

        new_ids = output_t[0, len(ids):].tolist()

        # --- Repetition detection ---
        # Stop immediately on any repeated token — even 2 in a row is a loop
        clean_ids  = []
        for i, tok in enumerate(new_ids):
            clean_ids.append(tok)

            # Stop if same token appears twice in a row
            if len(clean_ids) >= 2 and clean_ids[-1] == clean_ids[-2]:
                clean_ids = clean_ids[:-1]  # drop the repeat
                break

            # Stop if bigram repeats (A B A B)
            if len(clean_ids) >= 4:
                if clean_ids[-1] == clean_ids[-3] and clean_ids[-2] == clean_ids[-4]:
                    clean_ids = clean_ids[:-2]
                    break

        answer = self.tokenizer.decode(clean_ids, skip_special_tokens=True)

        # Post-decode safety: truncate at any new Q&A block marker
        for seq in STOP_SEQUENCES:
            if seq in answer:
                answer = answer[:answer.index(seq)]

        return answer.strip()

    # ------------------------------------------------------------------
    # Backwards compatibility
    # ------------------------------------------------------------------

    def generate(
        self,
        query:             str,
        retrieved_context: str   = "",
        max_new_tokens:    int   = 150,
        temperature:       float = 0.4,
        top_k:             int   = 20,
    ) -> str:
        if retrieved_context.strip():
            prompt = (
                f"Answer the following question based on the context:\n\n"
                f"Context:\n{retrieved_context.strip()}\n\n"
                f"Question: {query.strip()}\nAnswer:"
            )
        else:
            prompt = f"Question: {query.strip()}\nAnswer:"

        return self.generate_from_prompt(
            prompt         = prompt,
            max_new_tokens = max_new_tokens,
            temperature    = temperature,
            top_k          = top_k,
        )

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def model_info(self) -> dict:
        return {
            "parameters":  self.model.count_parameters(),
            "d_model":     self.model.d_model,
            "max_seq_len": self.model.max_seq_len,
            "device":      self.device,
            "vocab_size":  self.tokenizer.vocab_size,
            "tokenizer":   self.tokenizer.encoding_name,
        }