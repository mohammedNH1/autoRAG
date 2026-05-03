"""
decoder/inference.py
---------------------
RAGInference — the bridge between the RAG pipeline and the decoder LLM.

Your RAG pipeline already builds the full prompt (with context, citation
instructions, and the question). This class receives that ready-made prompt
directly and runs it through the decoder model.

Usage in your pipeline
-----------------------
    # Replace the Ollama block with this:

    from decoder.inference import RAGInference

    engine = RAGInference.get_instance()          # singleton, loaded once

    llm_response = engine.generate_from_prompt(
        prompt      = prompt,                     # your existing `prompt` variable
        temperature = temperature,
        top_p       = top_p,
        top_k       = top_k,
    )

The class handles:
  • Tokenisation          (prompt string → token ids via tiktoken)
  • Model inference       (token ids → generated ids)
  • Decoding              (generated ids → answer string)
"""

import os
import logging
import torch

from .model     import DecoderOnlyLM
from .tokenizer import TiktokenWrapper

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default model config
# vocab_size matches tiktoken cl100k_base (100,277 tokens)
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "vocab_size":  100_277,
    "d_model":     256,
    "n_heads":     8,
    "n_layers":    4,
    "d_ff":        1024,
    "max_seq_len": 512,
    "dropout":     0.0,      # always 0 at inference
}


class RAGInference:
    """
    High-level wrapper for the decoder LLM inside the AutoRAG system.

    Parameters
    ----------
    model     : DecoderOnlyLM instance
    tokenizer : TiktokenWrapper instance
    device    : 'cuda' | 'cpu'
    """

    _instance: "RAGInference" = None   # singleton

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
    # Singleton accessor — call this from your views / pipeline
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(
        cls,
        checkpoint_path: str = None,
        device: str = None,
    ) -> "RAGInference":
        """
        Returns the shared RAGInference instance, creating it on first call.

        If checkpoint_path is given → loads a trained model.
        Otherwise              → uses a fresh (untrained) model for dev/testing.
        """
        if cls._instance is None:
            if checkpoint_path and os.path.isdir(checkpoint_path):
                logger.info(f"[decoder] Loading from checkpoint: {checkpoint_path}")
                cls._instance = cls.from_pretrained(checkpoint_path, device)
            else:
                logger.info("[decoder] No checkpoint found — using untrained model")
                cls._instance = cls.from_scratch(device=device)
            logger.info(f"[decoder] Ready — {cls._instance.model_info()}")
        return cls._instance

    # ------------------------------------------------------------------
    # Factory: load a trained checkpoint
    # ------------------------------------------------------------------

    @classmethod
    def from_pretrained(
        cls,
        checkpoint_path: str,
        device: str = None,
    ) -> "RAGInference":
        """
        Load model + tokenizer from a checkpoint directory.

        Expected directory layout
        -------------------------
        checkpoint_path/
            model.pt        ← torch.save(model.state_dict(), ...)
            config.pt       ← torch.save(model_config_dict, ...)
            tokenizer.json  ← TiktokenWrapper.save(...)
        """
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"

        model_path     = os.path.join(checkpoint_path, "model.pt")
        config_path    = os.path.join(checkpoint_path, "config.pt")
        tokenizer_path = os.path.join(checkpoint_path, "tokenizer.json")

        config    = torch.load(config_path, map_location="cpu")
        tokenizer = TiktokenWrapper.load(tokenizer_path)
        config["vocab_size"] = tokenizer.vocab_size

        model             = DecoderOnlyLM(**config)
        model.load_state_dict(torch.load(model_path, map_location="cpu"))

        cls._instance = cls(model=model, tokenizer=tokenizer, device=device)
        return cls._instance

    # ------------------------------------------------------------------
    # Factory: fresh untrained model (for dev / testing)
    # ------------------------------------------------------------------

    @classmethod
    def from_scratch(
        cls,
        device: str = None,
        **model_kwargs,
    ) -> "RAGInference":
        """
        Build a randomly-initialised model with tiktoken vocab.
        Useful for wiring up the pipeline before you have a trained checkpoint.
        """
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"

        cfg           = {**DEFAULT_CONFIG, **model_kwargs}
        model         = DecoderOnlyLM(**cfg)
        tokenizer     = TiktokenWrapper()
        cls._instance = cls(model=model, tokenizer=tokenizer, device=device)
        return cls._instance

    # ------------------------------------------------------------------
    # Primary method: receive the ready-made prompt from your pipeline
    # ------------------------------------------------------------------

    def generate_from_prompt(
        self,
        prompt:         str,
        max_new_tokens: int   = 200,
        temperature:    float = 0.8,
        top_p:          float = 0.9,
        top_k:          int   = 40,
    ) -> str:
        """
        Generate text given a fully-constructed prompt string.

        This is the method to call from your RAG pipeline — it replaces
        the requests.post(...) call to Ollama.

        Parameters
        ----------
        prompt          : the complete prompt your pipeline already builds
                          (includes context, citation instructions, question)
        max_new_tokens  : how many new tokens to generate
        temperature     : sampling temperature  (lower = more focused)
        top_p           : nucleus sampling threshold (not used yet, reserved)
        top_k           : top-k sampling  (0 = greedy)

        Returns
        -------
        answer : str — the generated continuation (decoded, special tokens stripped)
        """
        # Tokenise — no extra BOS/EOS; the prompt is the full input
        ids     = self.tokenizer.encode(prompt, add_special_tokens=False)
        input_t = torch.tensor([ids], dtype=torch.long, device=self.device)

        # Truncate if the prompt alone already exceeds max_seq_len
        max_ctx = self.model.max_seq_len - max_new_tokens
        if input_t.shape[1] > max_ctx:
            logger.warning(
                f"[decoder] Prompt ({input_t.shape[1]} tokens) truncated to {max_ctx}"
            )
            input_t = input_t[:, -max_ctx:]
            ids     = ids[-max_ctx:]

        # Run generation
        output_t = self.model.generate(
            input_ids       = input_t,
            max_new_tokens  = max_new_tokens,
            temperature     = temperature,
            top_k           = top_k,
        )

        # Decode only the newly generated tokens (everything after the prompt)
        new_ids = output_t[0, len(ids):].tolist()
        answer  = self.tokenizer.decode(new_ids, skip_special_tokens=True)
        return answer.strip()

    # ------------------------------------------------------------------
    # Kept for backwards compatibility / direct use
    # ------------------------------------------------------------------

    def generate(
        self,
        query:             str,
        retrieved_context: str   = "",
        max_new_tokens:    int   = 200,
        temperature:       float = 0.8,
        top_k:             int   = 40,
    ) -> str:
        """
        Build a simple prompt internally and generate.
        Use generate_from_prompt() when your pipeline already has a prompt.
        """
        if retrieved_context.strip():
            prompt = (
                f"Answer the following question based on the context:\n\n"
                f"Context:\n{retrieved_context.strip()}\n\n"
                f"Question: {query.strip()}"
            )
        else:
            prompt = f"Question: {query.strip()}"

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