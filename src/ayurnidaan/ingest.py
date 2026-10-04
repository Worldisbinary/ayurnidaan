"""Fetch Kaggle sources into the raw zone and verify them against pinned checksums.

Raw files are immutable inputs: if a file on disk does not match the registry's
sha256 the pipeline refuses to run, so every artifact is traceable to exact bytes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .config import Registry, Source
from .logging_utils import get_logger

log = get_logger(__name__)


class ChecksumMismatch(RuntimeError):
    pass


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


@dataclass(frozen=True)
class RawFile:
    source: Source
    path: Path
    sha256: str


def fetch(source: Source, data_dir: Path, force: bool = False) -> Path:
    """Download one source (Kaggle API or direct URL) unless it is already cached."""
    target = source.path(data_dir)
    if target.exists() and not force:
        return target
    if source.url:
        import urllib.request

        target.parent.mkdir(parents=True, exist_ok=True)
        log.info("downloading", fields={"source": source.name, "url": source.url})
        tmp = target.with_suffix(target.suffix + ".part")
        with urllib.request.urlopen(source.url, timeout=120) as resp, tmp.open("wb") as fh:
            while block := resp.read(1 << 20):
                fh.write(block)
        tmp.replace(target)
        return target
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Install the `ingest` extra to download from Kaggle") from exc
    api = KaggleApi()
    api.authenticate()  # reads ~/.kaggle/kaggle.json or KAGGLE_USERNAME/KAGGLE_KEY
    out = data_dir / source.slug_dir
    out.mkdir(parents=True, exist_ok=True)
    log.info("downloading", fields={"source": source.name, "kaggle": source.kaggle})
    api.dataset_download_files(source.kaggle, path=str(out), unzip=True, quiet=True)
    if not target.exists():
        raise FileNotFoundError(f"{source.kaggle} did not contain {source.file}")
    return target


def verify(source: Source, data_dir: Path) -> RawFile:
    path = source.path(data_dir)
    if not path.exists():
        raise FileNotFoundError(f"{path} missing - run `ayur fetch` first")
    digest = sha256_of(path)
    if digest != source.sha256:
        raise ChecksumMismatch(
            f"{source.name}: expected {source.sha256[:12]}..., got {digest[:12]}... "
            "(upstream dataset changed; re-audit before updating the registry)"
        )
    return RawFile(source, path, digest)


def read_raw(raw: RawFile) -> pd.DataFrame:
    if raw.source.format == "xml":
        from .transform import epidemiology

        parser = {
            "orphanet_prevalence": epidemiology.parse_prevalence,
            "orphanet_names": epidemiology.parse_names,
        }[raw.source.name]
        return parser(raw.path)
    # Some Kaggle uploads are cp1252 with stray bytes; never fail ingestion on encoding.
    return pd.read_csv(raw.path, encoding_errors="replace", low_memory=False)


def fetch_all(registry: Registry, data_dir: Path, force: bool = False) -> list[Path]:
    return [fetch(s, data_dir, force) for s in registry.sources.values()]
