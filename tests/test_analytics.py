import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import adjusted_rand_score

from ayurnidaan.analytics import clusters, risk, screening, variables


def planted_docs(rng, n=300, groups=4, per=6):
    vocab = [f"g{g}_s{s}" for g in range(groups) for s in range(per)]
    docs, truth = [], []
    for i in range(n):
        g = i % groups
        docs.append(list(rng.choice(vocab[g * per : (g + 1) * per], 3, replace=False)))
        truth.append(f"system{g}")
    return docs, vocab, pd.Series(truth)


def test_npmi_properties():
    x = clusters.binary_matrix([["a", "b"], ["a", "b"], ["c"], ["c"]], ["a", "b", "c"])
    w, co = clusters.npmi(x)
    assert w[0, 1] == pytest.approx(1.0)  # always together
    assert w[0, 2] == -1.0  # never together
    assert co[0, 0] == 2


def test_consensus_clustering_recovers_planted_groups():
    rng = np.random.default_rng(0)
    docs, vocab, systems = planted_docs(rng)
    res = clusters.cluster_symptoms(docs, vocab, systems, n_boot=10, min_clusters=2, seed=0)
    truth = [int(t.split("_")[0][1:]) for t in vocab]
    assert adjusted_rand_score(truth, res.labels) == pytest.approx(1.0)
    assert res.nmi_body_system > 0.9 and res.nmi_p_value < 0.05


def test_jmi_skips_redundant_copy():
    rng = np.random.default_rng(0)
    y = rng.integers(0, 2, 2000)
    f1 = np.where(rng.random(2000) < 0.85, y, 1 - y)
    f2 = np.where(rng.random(2000) < 0.75, y, 1 - y)
    x = np.column_stack([f1, f1.copy(), f2, rng.integers(0, 2, 2000)])
    order = screening.jmi_rank(x, y)
    assert order[0] in (0, 1)
    assert order[1] == 2  # complementary feature beats the exact duplicate


def test_questionnaire_reduction_finds_signal_items():
    import synthetic

    df = synthetic.prakriti_assessment(400, np.random.default_rng(0), n_signal=4, n_items=10)
    qr = screening.reduce_questionnaire(df, "Dosha", n_splits=3, n_repeats=1)
    assert set(qr.ranking[:4]) == {"Item 01", "Item 02", "Item 03", "Item 04"}
    assert qr.recommended_k <= 6
    assert qr.recommended_accuracy >= qr.full_accuracy - 0.03


def test_adaptive_screener_concentrates_posterior():
    rng = np.random.default_rng(0)
    docs, vocab, systems = planted_docs(rng)
    x = clusters.binary_matrix(docs, vocab).toarray().astype(int)
    sc = screening.AdaptiveScreener.fit(x, systems, vocab, pool=vocab)
    answers = {}
    for _ in range(4):
        q, gain = sc.next_question(answers)
        assert gain > 0
        answers[q] = q.startswith("g2_")
    assert sc.top_systems(answers)[0][0] == "system2"


def test_cramers_v_extremes():
    perfect = pd.crosstab(pd.Series([0, 1] * 50), pd.Series([0, 1] * 50))
    assert variables.cramers_v(perfect) == pytest.approx(1.0, abs=0.02)


def test_variable_discovery_recovers_planted_drivers():
    import synthetic
    from ayurnidaan.transform import normalize, pii

    raw = synthetic.patient_intake(1500, np.random.default_rng(3))
    cohort = normalize.clean_patient_intake(pii.scrub(raw, ["Name"], "s", ["Name", "Age"]))
    rep, _ = variables.discover(cohort, seed=0)
    assert {"age", "family_history"} <= set(rep.predictive)
    tiers = rep.table.set_index("variable")["evidence_tier"]
    assert (tiers[["exercise", "meal_timing", "daily_routine"]] == "not supported").all()


def test_threshold_for_sensitivity():
    y = np.array([1] * 10 + [0] * 10)
    p = np.linspace(0, 1, 20)
    thr = risk.threshold_for_sensitivity(y, p, 0.8)
    assert ((p >= thr) & (y == 1)).sum() / 10 >= 0.8
