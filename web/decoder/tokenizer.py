"""
decoder/tokenizer.py
---------------------
Tokenizer wrapper around tiktoken (OpenAI's BPE tokenizer).

Supports two encodings:
  "cl100k_base"  → GPT-4 / GPT-3.5  (100,277 tokens)  ← default
  "r50k_base"    → GPT-2             (50,257 tokens)   ← used with load_gpt2.py

No training or vocab file needed. tiktoken downloads the encoding table
once and caches it locally (~5 MB).

Install:
    pip3 install tiktoken
"""

from typing import List
import tiktoken


ENCODING_NAME = "cl100k_base"

# Special token IDs per encoding.
# cl100k_base has <|im_start|> / <|im_end|> as built-in special tokens.
# r50k_base (GPT-2) uses <|endoftext|> (id=50256) for both BOS and EOS.
_SPECIAL_TOKENS = {
    "cl100k_base": {"bos": 100_264, "eos": 100_265},
    "r50k_base":   {"bos": 50_256,  "eos": 50_256 },
    "p50k_base":   {"bos": 50_256,  "eos": 50_256 },
}


class TiktokenWrapper:
    """
    Tokenizer wrapper around tiktoken.
    Supports cl100k_base (default) and r50k_base (GPT-2).

    Key properties
    --------------
    vocab_size : int   — total number of tokens
    bos_id     : int   — beginning-of-sequence token id
    eos_id     : int   — end-of-sequence token id
    pad_id     : int   — padding token id (= eos_id)
    encoding_name : str — which tiktoken encoding is active
    """

    def __init__(self, encoding_name: str = ENCODING_NAME):
        self._enc          = tiktoken.get_encoding(encoding_name)
        self.encoding_name = encoding_name
        _ids               = _SPECIAL_TOKENS.get(encoding_name, {"bos": 100_264, "eos": 100_265})
        self._bos_id       = _ids["bos"]
        self._eos_id       = _ids["eos"]

    # ------------------------------------------------------------------
    # Special token IDs
    # ------------------------------------------------------------------

    @property
    def bos_id(self) -> int:
        return self._bos_id

    @property
    def eos_id(self) -> int:
        return self._eos_id

    @property
    def pad_id(self) -> int:
        return self._eos_id   # pad = eos (standard convention)

    @property
    def vocab_size(self) -> int:
        return self._enc.n_vocab

    # ------------------------------------------------------------------
    # Encode / decode
    # ------------------------------------------------------------------

    def encode(self, text: str, add_special_tokens: bool = True) -> List[int]:
        """
        Convert a string to a list of BPE token IDs.

        Parameters
        ----------
        text                : input string
        add_special_tokens  : if True, prepend BOS and append EOS
        """
        ids = self._enc.encode(text, allowed_special="all")
        if add_special_tokens:
            ids = [self.bos_id] + ids + [self.eos_id]
        return ids

    def decode(self, ids: List[int], skip_special_tokens: bool = True) -> str:
        """
        Convert a list of token IDs back to a string.

        Parameters
        ----------
        ids                 : list of integer token ids
        skip_special_tokens : if True, removes BOS / EOS / PAD tokens
        """
        if skip_special_tokens:
            special = {self.bos_id, self.eos_id, self.pad_id}
            ids = [i for i in ids if i not in special]
        return self._enc.decode(ids)

    # ------------------------------------------------------------------
    # Compatibility shims
    # ------------------------------------------------------------------

    def build_vocab(self, text: str):
        """No-op — tiktoken vocab is fixed, no training needed."""
        pass

    def save(self, path: str):
        """Save the encoding name to a JSON file."""
        import json, os
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump({"encoding": self.encoding_name}, f)

    @classmethod
    def load(cls, path: str) -> "TiktokenWrapper":
        """Load from the JSON file written by save()."""
        import json
        with open(path) as f:
            data = json.load(f)
        return cls(encoding_name=data.get("encoding", ENCODING_NAME))