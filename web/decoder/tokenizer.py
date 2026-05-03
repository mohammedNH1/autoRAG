"""
decoder/tokenizer.py
---------------------
Tokenizer wrapper around tiktoken (OpenAI's BPE tokenizer).

Uses the "cl100k_base" encoding — the same one used by GPT-4 and GPT-3.5.
Vocabulary size: 100,277 tokens.

No training or vocab file needed. tiktoken downloads the encoding table
once and caches it locally (~5 MB).

Install:
    pip install tiktoken
"""

from typing import List
import tiktoken


# The encoding to use. Options:
#   "cl100k_base"  → GPT-4 / GPT-3.5  (100,277 tokens)  ← recommended
#   "p50k_base"    → GPT-3 Codex       (50,281 tokens)
#   "r50k_base"    → original GPT-2    (50,257 tokens)
ENCODING_NAME = "cl100k_base"

# tiktoken does not have explicit PAD/BOS/EOS tokens.
# We repurpose two unused high-range IDs for BOS and EOS,
# and define PAD as the same as EOS (standard practice).
# These IDs are outside the normal token range so they never clash.
_BOS_ID = 100_264   # <|im_start|>  (already in cl100k special tokens)
_EOS_ID = 100_265   # <|im_end|>    (already in cl100k special tokens)
_PAD_ID = _EOS_ID   # pad = eos  (common convention)


class TiktokenWrapper:
    """
    Drop-in replacement for the old CharTokenizer.
    Wraps tiktoken so the rest of the codebase (model.py, inference.py,
    train.py) works without any changes.

    Key properties
    --------------
    vocab_size : int   — total number of tokens (100,277 for cl100k_base)
    bos_id     : int   — beginning-of-sequence token id
    eos_id     : int   — end-of-sequence token id
    pad_id     : int   — padding token id (= eos_id)
    """

    def __init__(self, encoding_name: str = ENCODING_NAME):
        self._enc           = tiktoken.get_encoding(encoding_name)
        self.encoding_name  = encoding_name

    # ------------------------------------------------------------------
    # Special token IDs
    # ------------------------------------------------------------------

    @property
    def bos_id(self) -> int:
        return _BOS_ID

    @property
    def eos_id(self) -> int:
        return _EOS_ID

    @property
    def pad_id(self) -> int:
        return _PAD_ID

    @property
    def vocab_size(self) -> int:
        # n_vocab includes the special tokens already
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
        # allowed_special="all" so the <|im_start|>/<|im_end|> markers
        # are tokenised as single tokens rather than split character-by-character.
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
    # Compatibility shims (used by train.py)
    # ------------------------------------------------------------------

    def build_vocab(self, text: str):
        """No-op — tiktoken vocab is fixed, no training needed."""
        pass

    def save(self, path: str):
        """
        Save the encoding name to a small JSON file.
        (No need to store the full vocab — tiktoken fetches it automatically.)
        """
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