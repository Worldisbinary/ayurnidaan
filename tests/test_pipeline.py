import json

import duckdb
import pytest
import yaml

from ayurnidaan import ingest
from ayurnidaan.config import Settings, load_registry
from ayurnidaan.pipeline import run


def test_pipeline_publishes_all_artifacts(synthetic_settings, pipeline_run):
    out = synthetic_settings.artifacts_dir
    for name in [
        "warehouse.duckdb",
        "quality_report.json",
        "clusters.json",
        "screening.json",
        "variables.json",
        "model_card.json",
        "risk_model.joblib",
        "screener.joblib",
    ]:
        assert (out / name).exists(), name
    assert sorted(pipeline_run["admitted"]) == sorted(
        load_registry(synthetic_settings.sources_file).sources
    )


def test_warehouse_contents_and_lineage(synthetic_settings, pipeline_run):
    con = duckdb.connect(str(synthetic_settings.warehouse_path), read_only=True)
    try:
        cols = {r[0] for r in con.execute("DESCRIBE fact_patient_intake").fetchall()}
        assert "Name" not in cols and "patient_key" in cols  # PII never lands
        lineage = con.execute(
            "SELECT COUNT(*) FROM meta_lineage WHERE run_id = ?", [pipeline_run["run_id"]]
        ).fetchone()[0]
        assert lineage == 5
        assert con.execute("SELECT COUNT(*) FROM v_dosha_overview").fetchone()[0] == 7
        conflicts = con.execute(
            "SELECT COUNT(*) FROM dim_condition WHERE profile_conflict"
        ).fetchone()[0]
        assert conflicts == 2  # the planted copy-paste error (both rows of the pair)
    finally:
        con.close()


def test_symptom_clusters_match_planted_systems(synthetic_settings, pipeline_run):
    c = json.loads((synthetic_settings.artifacts_dir / "clusters.json").read_text())
    assert c["nmi_body_system"] > 0.6
    assert c["nmi_p_value"] < 0.05


def test_model_card_is_honest(synthetic_settings, pipeline_run):
    card = json.loads((synthetic_settings.artifacts_dir / "model_card.json").read_text())
    assert card["holdout"]["auc"] > 0.65
    assert card["n_train"] + card["n_holdout"] < 700  # declined-to-answer rows excluded
    assert "age" in card["features"]
    assert card["limitations"]


def test_checksum_mismatch_is_fatal(synthetic_settings, tmp_path):
    reg = yaml.safe_load(synthetic_settings.sources_file.read_text())
    reg["sources"]["patient_intake"]["sha256"] = "0" * 64
    bad = tmp_path / "sources.yaml"
    bad.write_text(yaml.safe_dump(reg))
    src = load_registry(bad)["patient_intake"]
    with pytest.raises(ingest.ChecksumMismatch):
        ingest.verify(src, synthetic_settings.data_dir)


def test_gate_rejection_of_required_source_aborts_run(synthetic_settings, tmp_path):
    reg = yaml.safe_load(synthetic_settings.sources_file.read_text())
    reg["quality_gate"] = {"max_duplicate_rate": -1.0}  # every source now "fails"
    bad = tmp_path / "sources.yaml"
    bad.write_text(yaml.safe_dump(reg))
    settings = Settings(
        data_dir=synthetic_settings.data_dir,
        artifacts_dir=tmp_path / "a",
        knowledge_dir=tmp_path / "k",
        sources_file=bad,
        pii_salt="x",
    )
    with pytest.raises(RuntimeError, match="Quality gate rejected"):
        run(settings, fast=True)
