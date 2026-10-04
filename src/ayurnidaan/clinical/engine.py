"""Assessment engine: one encounter's inputs -> a complete, explainable assessment.

Order of reasoning (mirrors Ayurvedic clinical method, with modern safety first):

1. Triage       - emergency red flags; positive -> stop, refer.
2. Prakriti     - constitution from the questionnaire.
3. Vikriti      - current imbalance from symptoms + pariksha + upashaya + agni.
4. Agni / Ama   - digestive pattern and Ama load.
5. Kala / Desha - season and habitat.
6. Differential - ranked conditions with evidence, then the next most informative
                  questions (adaptive interview).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import dosha, guidance, pariksha, red_flags
from .differential import DifferentialModel, Feedback
from .kala_desha import kala_desha
from .knowledge import KnowledgePack
from .symptom_search import SymptomIndex

DISCLAIMER = (
    "This is a screening and decision-support tool, not a diagnosis. Results are relative "
    "likelihoods among conditions in its knowledge base. A qualified practitioner must "
    "confirm any diagnosis before treatment."
)


@dataclass
class EncounterInput:
    age: float | None = None
    sex: str | None = None  # female | male | None
    on_date: date = field(default_factory=date.today)
    desha: str | None = None  # jangala | anupa | sadharana
    red_flag_checklist: dict[str, bool] = field(default_factory=dict)
    symptoms: dict[str, bool] = field(default_factory=dict)  # canonical term -> present
    free_text_symptoms: list[str] = field(default_factory=list)
    prakriti_answers: dict[str, str] = field(default_factory=dict)
    examination: dict[str, str] = field(default_factory=dict)
    aggravating: list[str] = field(default_factory=list)
    relieving: list[str] = field(default_factory=list)
    agni: str | None = None
    skip_red_flags: bool = False  # only for offline evaluation


class AssessmentEngine:
    def __init__(self, pack: KnowledgePack, feedback: Feedback | None = None):
        self.pack = pack
        self.model = DifferentialModel(pack, feedback)
        self.search = SymptomIndex(pack.symptoms)

    @classmethod
    def from_directory(cls, directory: Path, feedback: Feedback | None = None) -> AssessmentEngine:
        return cls(KnowledgePack.load(directory), feedback)

    @property
    def version(self) -> str:
        fb = self.model.feedback.n_cases
        return f"{self.pack.version}+fb{fb}"

    def assess(self, enc: EncounterInput, top: int = 10, n_questions: int = 3) -> dict:
        answers = dict(enc.symptoms)
        mapped = []
        for text in enc.free_text_symptoms:
            hit = self.search.best(text)
            if hit:
                answers.setdefault(hit, True)
                mapped.append({"input": text, "matched": hit})
            else:
                mapped.append({"input": text, "matched": None})

        tri = red_flags.triage(enc.red_flag_checklist, answers)
        result = {
            "engine_version": self.version,
            "triage": {"level": tri.level, "flags": tri.flags},
            "free_text_mapping": mapped,
            "disclaimer": DISCLAIMER,
        }
        if tri.stop and not enc.skip_red_flags:
            result["stopped"] = True
            return result

        present = [s for s, v in answers.items() if v]
        prak = dosha.prakriti(self.pack.prakriti, enc.prakriti_answers)
        extra, trail = pariksha.dosha_evidence(
            enc.examination, enc.aggravating, enc.relieving, enc.agni
        )
        vik = dosha.vikriti(self.pack.vikriti, present, extra, trail)
        kd = kala_desha(enc.on_date, enc.desha)

        parts = self.model.log_scores(answers, enc.age, enc.sex, vik, prak, kd)
        post = self.model.posterior(parts)
        questions = self.model.next_questions(post, answers, k=n_questions)
        result.update(
            {
                "stopped": False,
                "prakriti": prak.to_dict() if prak else None,
                "vikriti": vik.to_dict() if vik else None,
                "agni": pariksha.AGNI[enc.agni][0] if enc.agni in pariksha.AGNI else None,
                "ama": pariksha.ama_assessment(set(present), enc.examination),
                "kala_desha": kd.to_dict(),
                "differential": self.model.rank(post, parts, answers, top=top),
                "next_questions": [
                    {"symptom": s, "information_gain_bits": round(g, 4)} for s, g in questions
                ],
                "answered_symptoms": len(answers),
                "guidance": guidance.patient_guidance(kd.ritu, vik.dominant if vik else None),
            }
        )
        return result
