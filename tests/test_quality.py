import numpy as np
import pandas as pd
import pytest

from ayurnidaan import quality
from ayurnidaan.config import QualityGate, Source

GATE = QualityGate()


def src(**kw) -> Source:
    base = {"name": "s", "kaggle": "a/b", "file": "f.csv", "sha256": "0" * 64, "role": "assessment"}
    return Source(**(base | kw))


def test_mutual_information_bounds():
    x = np.array([0, 0, 1, 1] * 50)
    assert quality.mutual_information(x, x) == pytest.approx(np.log(2))
    assert quality.mutual_information(x, np.array([0, 1] * 100)) == pytest.approx(0.0, abs=1e-12)


def test_noise_feature_detection_separates_signal_from_noise():
    rng = np.random.default_rng(0)
    y = rng.integers(0, 3, 600)
    df = pd.DataFrame(
        {
            "signal": np.where(rng.random(600) < 0.8, y, rng.integers(0, 3, 600)),
            "noise": rng.integers(0, 3, 600),
            "label": y,
        }
    )
    feats, noise = quality.detect_noise_features(df, "label", alpha=0.01)
    assert set(feats) == {"signal", "noise"}
    assert noise == ["noise"]


def test_padded_duplicates_are_caught_by_excess_signal_duplicate_rate():
    """The 'Updated Prakriti' pattern: 50 real rows x 12 copies + random padding columns."""
    rng = np.random.default_rng(1)
    base = pd.DataFrame({f"f{i}": rng.integers(0, 3, 50) for i in range(8)})
    base["label"] = base["f0"]
    padded = pd.concat([base] * 12, ignore_index=True)
    for j in range(5):
        padded[f"pad{j}"] = rng.integers(0, 3, len(padded))
    rep = quality.audit(padded, src(label="label"), GATE)
    checks = {c.check: c for c in rep.checks}
    assert checks["excess_duplicate_rate"].passed  # padding hides exact duplicates...
    assert not checks["excess_signal_duplicate_rate"].passed  # ...but not signal duplicates
    assert not rep.passed


def test_legitimate_collisions_are_not_flagged():
    """Few low-cardinality items -> chance collisions; must not be read as padding."""
    rng = np.random.default_rng(2)
    y = rng.integers(0, 3, 3000)
    df = pd.DataFrame(
        {f"f{i}": np.where(rng.random(3000) < 0.7, y, rng.integers(0, 3, 3000)) for i in range(4)}
    )
    df["label"] = y
    rep = quality.audit(df, src(label="label"), GATE)
    assert rep.passed


def test_repeated_rows_without_padding_fail_duplicate_check():
    """The 'Prakriti small' pattern: 100 unique rows repeated 12x."""
    rng = np.random.default_rng(3)
    base = pd.DataFrame({f"f{i}": rng.integers(0, 3, 100) for i in range(15)})
    base["label"] = base["f0"]
    rep = quality.audit(pd.concat([base] * 12, ignore_index=True), src(label="label"), GATE)
    assert not {c.check: c for c in rep.checks}["excess_duplicate_rate"].passed


def test_templated_text_fails_uniqueness():
    df = pd.DataFrame({"Problem": [f"p{i}" for i in range(100)], "Symptoms": ["a; b", "c; d"] * 50})
    rep = quality.audit(
        df, src(role="knowledge_base", text_column="Symptoms", entity_column="Problem"), GATE
    )
    assert not rep.passed


def test_pii_only_checked_for_person_level_sources():
    df = pd.DataFrame({"Name": [f"n{i}" for i in range(20)], "x": [1, 2] * 10})
    assert quality.audit(df, src(role="patient_cohort"), GATE).pii_columns == ["Name"]
    assert quality.audit(df, src(role="knowledge_base"), GATE).pii_columns == []


def test_conflicting_rows_flags_copy_paste_errors_not_paraphrases():
    df = pd.DataFrame(
        {
            "e": ["Apasmara", "Apasmara", "Asthma", "Asthma", "Asthma"],
            "t": [
                "Convulsions, loss of consciousness",
                "Recurrent seizures, loss of consciousness",
                "Wheezing, shortness of breath",
                "Wheezing, chest tightness",
                "Vision loss, blurred focus",
            ],
        }
    )
    assert quality.conflicting_rows(df, "e", "t") == [4]
