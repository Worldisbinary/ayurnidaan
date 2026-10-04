import numpy as np
import pandas as pd
import pytest

from ayurnidaan.transform import normalize, pii, symptoms, terminology


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Vata", "vata"),
        ("vata+pitta", "vata-pitta"),
        ("Pitta-Vata", "vata-pitta"),
        ("Kapha, Vata", "vata-kapha"),
        ("Tridosha", "tridosha"),
        ("Vata/Pitta/Kapha", "tridosha"),
        ("Pitta/Rakta", "pitta"),
        ("Agantuja", None),
        ("i don't know", None),
        (None, None),
        (np.nan, None),
    ],
)
def test_canonical_dosha(raw, expected):
    assert normalize.canonical_dosha(raw) == expected


def test_dosha_components_handles_missing():
    assert normalize.dosha_components("tridosha") == ["vata", "pitta", "kapha"]
    assert normalize.dosha_components(np.nan) == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Gastrointestinal", "digestive"),
        ("Nose/Head", "ent"),
        ("Nervous/Musculoskeletal", "nervous"),
        ("Gynaecology", "reproductive"),
        (None, "unspecified"),
        ("Astrology", "other"),
    ],
)
def test_canonical_body_system(raw, expected):
    assert normalize.canonical_body_system(raw) == expected


def test_pseudonymize_is_keyed_stable_and_case_insensitive():
    a = pii.pseudonymize("Riya Patel", "k1")
    assert a == pii.pseudonymize("  riya   PATEL ", "k1")
    assert a != pii.pseudonymize("Riya Patel", "k2")
    assert "riya" not in a.lower()


def test_scrub_drops_pii_and_keeps_unique_record_ids():
    df = pd.DataFrame({"Name": ["A", "A", "B"], "Age": [30, 30, 40], "x": [1, 2, 3]})
    out = pii.scrub(df, ["Name"], "salt", ["Name", "Age"])
    assert "Name" not in out.columns
    assert out["record_id"].is_unique
    assert out["patient_key"].iloc[0] == out["patient_key"].iloc[1]  # same identity


def test_split_and_normalize_symptoms():
    got = symptoms.split_symptoms(
        "Severe eye pain (temporal), Haematuria; Breathlessness and Oedema / hard, Watery eyes"
    )
    assert got == ["eye pain", "hematuria", "shortness of breath", "edema", "lacrimation"]


def test_vocabulary_plural_folding_and_backoff():
    docs = (
        [["joint pain", "fever"]] * 3
        + [["joint pains"], ["redness of eye", "fever"]]
        + [["redness"]] * 3
    )
    v = symptoms.SymptomVocabulary(min_df=3).fit(docs)
    assert v.canonical["joint pains"] == "joint pain"
    assert v.canonical["redness of eye"] == "redness"
    assert v.backoff == {"redness of eye": "redness"}
    assert v.transform(["redness of eye", "rare thing"]) == ["redness"]


def test_safe_merge_blocks_meaning_flips():
    assert not symptoms._safe_merge("hypotension", "hypertension")
    assert not symptoms._safe_merge("type 1 diabetes", "type 2 diabetes")
    assert symptoms._safe_merge("joint pains", "joint pain")


def test_phonetic_key_unifies_romanisations():
    assert terminology.phonetic_key("Abhisyanda") == terminology.phonetic_key("abhiṣyandaḥ")
    assert terminology.phonetic_key("Vataja Visarpa") == terminology.phonetic_key("vātajavisarpaḥ")


def test_namc_link_guards_reject_meaning_flips():
    namc = pd.DataFrame(
        {
            "NAMC_CODE": ["EB-10.12", "ED-10.4"],
            "NAMC_term": ["bastiSUlaH", "vAtajavisarpaH"],
            "NAMC_term_diacritical": ["bastiśūlaḥ", "vātajavisarpaḥ"],
        }
    )
    out = terminology.link_namc(pd.Series(["Asthisula", "Vataja Visarpa"]), namc)
    assert out["namc_tier"].tolist() == ["unlinked", "exact"]
    assert out["namc_code"].iloc[1] == "ED-10.4"
