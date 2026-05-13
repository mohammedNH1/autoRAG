"""
Workspace API key generation and hashing.

The raw key is shown to the owner exactly once at generation time and
never persisted. The database only ever stores the SHA-256 hex digest,
so a database leak cannot grant access to any workspace.
"""

import hashlib
import secrets


API_KEY_PREFIX = "autorag_"
# 32 random bytes → 43 urlsafe chars; combined with the prefix gives a
# ~50-char token that is easy to copy and hard to brute force.
API_KEY_RANDOM_BYTES = 32


def generate_api_key():
    """Return a fresh raw API key. Only ever returned, never stored."""
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(API_KEY_RANDOM_BYTES)}"


def hash_api_key(raw_key):
    """Return the SHA-256 hex digest used as the lookup key in the DB."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def looks_like_api_key(value):
    """Cheap shape check before doing a DB lookup."""
    return isinstance(value, str) and value.startswith(API_KEY_PREFIX) and len(value) > len(API_KEY_PREFIX) + 8
