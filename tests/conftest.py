from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
warnings.filterwarnings("ignore")

import synthetic  # noqa: E402
from ayurnidaan.config import Settings  # noqa: E402

REAL_DATA = Path(__file__).resolve().parents[1] / "data" / "raw"


@pytest.fixture(scope="session")
def synthetic_settings(tmp_path_factory) -> Settings:
    root = tmp_path_factory.mktemp("synthetic")
    registry = synthetic.build(root)
    return Settings(
        data_dir=root / "raw",
        artifacts_dir=root / "artifacts",
        knowledge_dir=root / "knowledge_pack",
        sources_file=registry,
        pii_salt="test-salt",
        seed=0,
    )


@pytest.fixture(scope="session")
def pipeline_run(synthetic_settings):
    """Run the whole pipeline once on synthetic data; tests share the artifacts."""
    from ayurnidaan.pipeline import run

    return run(synthetic_settings, fast=True)
