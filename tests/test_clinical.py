from datetime import date

import pandas as pd
import pytest

from ayurnidaan.clinical import dosha, kala_desha, pariksha, red_flags
from ayurnidaan.clinical.demographics import AgeRange, parse_age, parse_sex
from ayurnidaan.clinical.differential import DifferentialModel, Feedback
from ayurnidaan.clinical.engine import AssessmentEngine, EncounterInput
from ayurnidaan.clinical.knowledge import KnowledgePack
from ayurnidaan.evidence import query_name, regional_weight
from ayurnidaan.transform import epidemiology

NO_FLAGS = {f.code: False for f in red_flags.CHECKLIST}


@pytest.fixture(scope="module")
def pack(synthetic_settings, pipeline_run) -> KnowledgePack:
    return KnowledgePack.load(synthetic_settings.knowledge_dir)


@pytest.fixture(scope="module")
def engine(pack) -> AssessmentEngine:
    return AssessmentEngine(pack)


# --- kala / desha ------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("day", "ritu"),
    [
        (date(2026, 1, 1), "hemanta"),
        (date(2026, 1, 20), "shishira"),
        (date(2026, 4, 1), "vasanta"),
        (date(2026, 6, 1), "grishma"),
        (date(2026, 8, 1), "varsha"),
        (date(2026, 10, 1), "sharad"),
        (date(2026, 12, 1), "hemanta"),
    ],
)
def test_ritu_calendar(day, ritu):
    assert kala_desha.ritu_for(day) == ritu


def test_dosha_cycle_follows_classical_table():
    assert kala_desha.dosha_states("varsha") == {
        "vata": "prakopa",
        "pitta": "chaya",
        "kapha": "neutral",
    }
    assert kala_desha.dosha_states("vasanta")["kapha"] == "prakopa"
    assert kala_desha.dosha_states("sharad")["pitta"] == "prakopa"


@pytest.mark.parametrize(
    ("precip", "rh", "desha"),
    [
        (206, 48, "jangala"),
        (519, 56, "jangala"),
        (1035, 69, "sadharana"),
        (2953, 82, "anupa"),
        (900, 80, "anupa"),
    ],
)
def test_desha_classification(precip, rh, desha):
    assert kala_desha.classify_desha(precip, rh) == desha


# --- demographics ------------------------------------------------------------------------
def test_age_parsing_and_soft_likelihood():
    assert parse_age("Adults 30–60") == AgeRange(30, 60)
    assert parse_age("Infants/children") == AgeRange(0, 18)
    assert parse_age("Post-partum females (within 6 weeks)") == AgeRange(15, 49)
    assert parse_age("Any age") == AgeRange()
    r = AgeRange(30, 60)
    assert (
        r.likelihood(45) == 1.0
        and r.likelihood(5) == pytest.approx(0.15)
        and 0.15 < r.likelihood(65) < 1
    )


@pytest.mark.parametrize(
    ("text", "female", "male"),
    [
        ("Female", 1.0, 0.02),
        ("Males only", 0.02, 1.0),
        ("Females more common", 1.0, 0.6),
        ("Males more in trauma, females in osteoporotic", 1.0, 1.0),
        ("Males much more common, post-menopausal women", 1.0, 1.0),
        ("Both genders", 1.0, 1.0),
    ],
)
def test_sex_parsing_handles_mixed_statements(text, female, male):
    w = parse_sex(text)
    assert (w.female, w.male) == (female, male)


# --- red flags -------------------------------------------------------------------------------
def test_checklist_positive_stops_everything(engine):
    res = engine.assess(
        EncounterInput(red_flag_checklist=NO_FLAGS | {"stroke": True}, symptoms={"cough": True})
    )
    assert res["stopped"] and res["triage"]["level"] == "emergency"
    assert "differential" not in res


def test_symptom_trigger_escalates_to_urgent_without_stopping(engine):
    res = engine.assess(EncounterInput(red_flag_checklist=NO_FLAGS, symptoms={"chest pain": True}))
    assert res["triage"]["level"] == "urgent" and not res["stopped"]


# --- dosha ----------------------------------------------------------------------------------
def test_vikriti_is_tempered_and_uses_examination(pack):
    some = [s["term"] for s in pack.symptoms[:4]]
    v = dosha.vikriti(pack.vikriti, some)
    raw = dosha.vikriti(pack.vikriti, some, temperature=1.0)
    assert v is not None and max(v.shares.values()) < max(raw.shares.values())  # sqrt(n) tempering
    extra, trail = pariksha.dosha_evidence(
        {"nadi": "sarpa_vata"}, ["wind_dryness"], [], "irregular"
    )
    assert extra["vata"] == pytest.approx(1.2 + 0.8 + 0.8)
    v2 = dosha.vikriti(pack.vikriti, some, extra, trail)
    assert v2.shares["vata"] > v.shares["vata"]


def test_prakriti_from_exported_coefficients(pack):
    answers = {q["id"]: q["options"][0]["value"] for q in pack.prakriti["questions"]}
    p = dosha.prakriti(pack.prakriti, answers)
    assert p.answered == len(answers) and sum(p.shares.values()) == pytest.approx(1)
    assert dosha.prakriti(pack.prakriti, {}) is None


# --- differential ---------------------------------------------------------------------------
def test_differential_recovers_planted_system(engine):
    res = engine.assess(
        EncounterInput(
            age=40,
            sex="female",
            red_flag_checklist=NO_FLAGS,
            symptoms={"cough": True, "wheezing": True, "sputum": True},
        )
    )
    top = res["differential"][0]
    assert top["body_system"] in {"respiratory", "unspecified"}
    assert {"cough", "wheezing"} <= set(top["evidence"]["supporting"])
    assert res["next_questions"] and all(
        q["symptom"] not in {"cough", "wheezing", "sputum"} for q in res["next_questions"]
    )


def test_free_text_is_mapped_or_abstained(engine):
    res = engine.assess(
        EncounterInput(
            red_flag_checklist=NO_FLAGS, free_text_symptoms=["Itching!!", "zzqq nonsense"]
        )
    )
    mapping = {m["input"]: m["matched"] for m in res["free_text_mapping"]}
    assert mapping["Itching!!"] == "itching" and mapping["zzqq nonsense"] is None


def test_feedback_shifts_ranking_toward_confirmed_condition(pack):
    base = DifferentialModel(pack)
    target = base.conditions[5]
    answers = {target["symptoms"][0]: True}
    before = base.posterior(base.log_scores(answers))[5]
    fb = Feedback.from_cases([{"condition_id": target["id"], "answers": answers}] * 15)
    learned = DifferentialModel(pack, fb)
    after = learned.posterior(learned.log_scores(answers))[learned.c_index[target["id"]]]
    assert after > before


def test_unasked_symptoms_are_not_treated_as_absent(pack):
    m = DifferentialModel(pack)
    s = m.terms[0]
    assert m.log_scores({s: True})["symptoms"].shape == (len(m.conditions),)
    # asking nothing gives a flat symptom term
    assert (m.log_scores({})["symptoms"] == 0).all()


# --- external sources -------------------------------------------------------------------------
def test_orphanet_geography_rule():
    prev = pd.DataFrame(
        [
            {
                "orphacode": "1",
                "name": "Cholera",
                "type": "Point prevalence",
                "class": "<1 / 1 000 000",
                "geography": "Europe",
                "validation": "Validated",
            },
            {
                "orphacode": "2",
                "name": "Tuberculosis",
                "type": "Annual incidence",
                "class": "1-9 / 100 000",
                "geography": "Europe",
                "validation": "Validated",
            },
            {
                "orphacode": "2",
                "name": "Tuberculosis",
                "type": "Annual incidence",
                "class": ">1 / 1000",
                "geography": "India",
                "validation": "Validated",
            },
            {
                "orphacode": "3",
                "name": "Ebola hemorrhagic fever",
                "type": "Cases/families",
                "class": None,
                "geography": "Worldwide",
                "validation": "Validated",
            },
        ]
    )
    priors = epidemiology.disorder_priors(prev)
    assert "1" not in priors  # Europe-only: no adjustment for an Indian population
    assert priors["2"]["weight"] == 1.0 and priors["2"]["geography"] == "India"
    assert priors["3"]["weight"] < 0.05
    names = pd.DataFrame(
        [
            {"orphacode": "3", "name": "Ebola hemorrhagic fever", "is_synonym": False},
            {"orphacode": "2", "name": "Tuberculosis", "is_synonym": False},
        ]
    )
    links = epidemiology.link_conditions(
        pd.Series(["Ebola", "Psoriasis"]), pd.Series(["Ebola", "Psoriasis"]), names, priors
    )
    assert links[0]["orphacode"] == "3" and links[1] is None


def test_regional_weight_and_query_name():
    assert (
        regional_weight({"hits_all": 1319, "hits_india": 8}) < 0.5
    )  # Rocky Mountain spotted fever
    assert regional_weight({"hits_all": 7972, "hits_india": 1183}) == 1.0  # dengue
    assert regional_weight({"hits_all": 5, "hits_india": 0}) == 1.0  # too little evidence
    assert (
        query_name(
            {
                "source": "condition_kb_classical",
                "modern_equivalent": "Acute/chronic suppurative otitis media",
                "name": "x",
            }
        )
        == "chronic suppurative otitis media"
    )


def test_regional_prior_applies_only_to_endemic_type_conditions():
    from ayurnidaan.evidence import is_endemic_type

    assert is_endemic_type("Dengue Fever") and is_endemic_type("Schistosomiasis")
    assert is_endemic_type("Rocky Mountain Spotted Fever")
    assert not is_endemic_type("Raynaud's Disease") and not is_endemic_type("Psoriasis")


def test_duplicate_names_are_not_double_counted(pack):
    m = DifferentialModel(pack)
    parts = m.log_scores({m.terms[0]: True})
    ranked = m.rank(m.posterior(parts), parts, {m.terms[0]: True}, top=20)
    names = [d["name"].casefold() for d in ranked]
    assert len(names) == len(set(names))
    likes = [d["likelihood"] for d in ranked]
    assert likes == sorted(likes, reverse=True)
