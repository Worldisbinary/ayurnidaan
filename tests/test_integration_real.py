"""Checks against the real Kaggle files; skipped when they are not on disk (e.g. CI)."""

import pytest

from ayurnidaan import ingest, quality
from ayurnidaan.config import PROJECT_ROOT, load_registry

from .conftest import REAL_DATA

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not any(REAL_DATA.glob("*/*.csv")), reason="real Kaggle data not present"),
]


def test_quality_gate_verdicts_on_real_sources():
    reg = load_registry(PROJECT_ROOT / "configs" / "sources.yaml")
    verdicts = {}
    for src in reg.sources.values():
        df = ingest.read_raw(ingest.verify(src, REAL_DATA))
        verdicts[src.name] = quality.audit(df, src, reg.quality_gate).passed
    assert verdicts == {
        "patient_intake": True,
        "prakriti_assessment": True,
        "condition_kb_classical": True,
        "condition_kb_modern": True,
        "namc_terminology": True,
        "orphanet_prevalence": True,
        "orphanet_names": True,
        "prakriti_small": False,
        "prakriti_updated": False,
        "ayurveda_healthcare_10k": False,
    }
