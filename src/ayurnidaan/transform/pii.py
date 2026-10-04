"""PII handling: direct identifiers never leave the transform layer.

Names are replaced by a keyed HMAC-SHA256 pseudonym. The key (``AYUR_PII_SALT``) lives
outside the repo, so pseudonyms are stable across runs (re-ingestion is idempotent)
but cannot be reversed by dictionary attack without the key.
"""

from __future__ import annotations

import hashlib
import hmac
import unicodedata

import pandas as pd


def _canonical(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    return " ".join(text.split())


def pseudonymize(value: str, salt: str, length: int = 16) -> str:
    digest = hmac.new(salt.encode(), _canonical(value).encode(), hashlib.sha256).hexdigest()
    return f"p_{digest[:length]}"


def scrub(df: pd.DataFrame, pii_columns: list[str], salt: str, key_from: list[str]) -> pd.DataFrame:
    """Drop PII columns, adding two pseudonymous keys.

    * ``patient_key`` - identity pseudonym from ``key_from`` (name + stable attributes,
      since names alone collide). It may repeat: the same identity can submit twice.
    * ``record_id``  - unique per submitted row (keyed hash of the full raw record).
    """
    out = df.copy()
    identity = out[key_from].astype(str).agg("|".join, axis=1)
    full_row = out.astype(str).agg("|".join, axis=1) + "|" + out.index.astype(str)
    out.insert(0, "record_id", full_row.map(lambda v: pseudonymize(v, salt, length=20)))
    out.insert(1, "patient_key", identity.map(lambda v: pseudonymize(v, salt)))
    return out.drop(columns=pii_columns)
