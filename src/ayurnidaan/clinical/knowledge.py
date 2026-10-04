"""Knowledge pack: the PII-free, versioned bundle the production engine runs on.

The pipeline builds it from the warehouse; it is committed to git so the deployed API
never needs raw Kaggle files (one of which contains real names). Everything is plain
JSON - no pickles - so it loads identically under any Python/library version.

    knowledge_pack/
      manifest.json     version, build time, source checksums, counts, metrics
      conditions.json   profiles, dosha, demographics, NAMC code, references
      symptoms.json     canonical vocabulary, document frequency, cluster, aliases
      prakriti.json     constitution questionnaire + multinomial-logit coefficients
      vikriti.json      per-symptom dosha log-likelihood ratios
      evidence.json     literature per condition (Europe PMC), optional
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score
from sklearn.preprocessing import OneHotEncoder

from ..transform import normalize
from .demographics import parse_age, parse_sex

PACK_VERSION = 1

# Patient-facing wording for the Prakriti items the screening analysis selected.
PRAKRITI_QUESTIONS = {
    "pace_of_performing_work": "How fast do you usually do things (walk, talk, work)?",
    "quality_of_voice": "How would you describe your voice?",
    "body_energy": "How is your physical energy through the day?",
    "body_frame": "What is your body frame?",
    "hunger": "How is your hunger / appetite pattern?",
    "type_of_hair": "What is your natural hair type?",
    "joints": "How are your joints?",
    "mental_activity": "How is your mind usually?",
    "body_odor": "How strong is your natural body odour?",
}


def _json_safe(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o))


def _write(path: Path, obj) -> str:
    text = json.dumps(obj, ensure_ascii=False, indent=1, default=_json_safe, sort_keys=True)
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode()).hexdigest()


# --- builders ---------------------------------------------------------------------------
def build_conditions(
    conditions: pd.DataFrame, docs: list[list[str]], literature: dict | None = None
) -> list[dict]:
    """``literature``: Europe PMC cache keyed by query name (see evidence.py), optional."""
    from .. import evidence as ev

    out = []
    for row, symptoms in zip(conditions.itertuples(index=False), docs, strict=True):
        age = parse_age(row.age_text)
        sex = parse_sex(row.sex_text, row.age_text)
        out.append(
            {
                "id": row.condition_id,
                "source": row.source,
                "name": row.name,
                "modern_equivalent": row.modern_equivalent,
                "body_system": row.body_system,
                "dosha": row.dosha if isinstance(row.dosha, str) else None,
                "dosha_components": normalize.dosha_components(row.dosha),
                "prognosis": row.prognosis if isinstance(row.prognosis, str) else None,
                "age": [age.low, age.high],
                "sex_weight": {"female": sex.female, "male": sex.male},
                "symptoms": symptoms,
                "cluster": int(row.primary_cluster),
                "namc": {"code": row.namc_code, "term": row.namc_term, "tier": row.namc_tier}
                if isinstance(row.namc_code, str)
                else None,
                "profile_conflict": bool(row.profile_conflict),
                # Orphanet geography-aware prevalence prior (None = not a known rare disorder)
                "prevalence": row.prevalence if isinstance(row.prevalence, dict) else None,
                "prior_weight": row.prevalence["weight"]
                if isinstance(row.prevalence, dict)
                else 1.0,
                "practitioner_reference": json.loads(row.practitioner_reference)
                if isinstance(row.practitioner_reference, str)
                else {},
                "patient_guidance": json.loads(row.patient_guidance)
                if isinstance(row.patient_guidance, str)
                else {},
            }
        )
        c = out[-1]
        c["evidence_key"] = ev.query_name(c)
        entry = (literature or {}).get(c["evidence_key"])
        # Endemicity only makes sense for infections / environmental toxins; a non-infectious
        # disease with little Indian literature (e.g. Raynaud's) is under-studied, not absent.
        regional = (
            ev.regional_weight(entry)
            if c["source"] == "condition_kb_modern" and ev.is_endemic_type(c["name"])
            else 1.0
        )
        c["literature"] = (
            None
            if entry is None
            else {
                "hits_all": entry["hits_all"],
                "hits_india": entry["hits_india"],
                "hits_ayurveda": entry["hits_ayurveda"],
                "regional_weight": regional,
            }
        )
        c["prior_weight"] = round(c["prior_weight"] * regional, 4)
    return out


def build_evidence(conditions: list[dict], literature: dict) -> dict:
    """Top Ayurveda-related papers per evidence key, for the practitioner view."""
    keys = {c["evidence_key"] for c in conditions}
    return {
        k: {"hits_ayurveda": v["hits_ayurveda"], "papers": v["top_ayurveda_papers"]}
        for k, v in literature.items()
        if k in keys
    }


def build_symptoms(vocab, sym_table: pd.DataFrame) -> dict:
    terms = vocab.terms
    max_df = max(vocab.doc_freq[t] for t in terms)
    cluster = dict(zip(sym_table["symptom"], sym_table["cluster_id"], strict=True))
    aliases: dict[str, list[str]] = {}
    for variant, canon in vocab.aliases():
        if canon in vocab.doc_freq and vocab.doc_freq[canon] >= vocab.min_df:
            aliases.setdefault(canon, []).append(variant)
    return {
        "terms": [
            {
                "term": t,
                "doc_freq": vocab.doc_freq[t],
                # background rate: chance a condition shows the symptom without listing it
                "background": round(0.02 + 0.08 * vocab.doc_freq[t] / max_df, 4),
                "cluster": int(cluster.get(t, -1)),
                "aliases": sorted(aliases.get(t, []))[:25],
            }
            for t in terms
        ]
    }


def build_prakriti(assessments: pd.DataFrame, items: list[str], seed: int = 42) -> dict:
    """Multinomial logit on the selected questionnaire items, exported as coefficients."""
    x = assessments[items].astype(str)
    y = assessments["dosha"]
    enc = OneHotEncoder(handle_unknown="ignore", sparse_output=False).fit(x)
    clf = LogisticRegression(max_iter=3000, C=1.0)
    cv_acc = float(cross_val_score(clf, enc.transform(x), y, cv=5).mean())
    clf.fit(enc.transform(x), y)
    questions = []
    col = 0
    for item, cats in zip(items, enc.categories_, strict=True):
        options = []
        for cat in cats:
            options.append(
                {
                    "value": str(cat),
                    "weights": dict(zip(clf.classes_, clf.coef_[:, col], strict=True)),
                }
            )
            col += 1
        questions.append(
            {
                "id": item,
                "question": PRAKRITI_QUESTIONS.get(item, item.replace("_", " ").capitalize() + "?"),
                "options": options,
            }
        )
    return {
        "classes": list(clf.classes_),
        "intercept": dict(zip(clf.classes_, clf.intercept_, strict=True)),
        "questions": questions,
        "cv_accuracy": cv_acc,
        "n_train": len(y),
    }


def build_vikriti(conditions: list[dict], terms: list[str], m: float = 5.0) -> dict:
    """Per-symptom log-likelihood ratio for each dosha component.

    P(dosha d involved | symptom s) is estimated from conditions listing s, shrunk
    toward the base rate with m pseudo-observations; the LLR is its logit minus the
    base-rate logit. Positive = the symptom points toward that dosha.
    """
    known = [c for c in conditions if c["dosha_components"] and not c["profile_conflict"]]
    base = {d: np.mean([d in c["dosha_components"] for c in known]) for d in normalize.DOSHAS}
    logit = lambda p: float(np.log(p / (1 - p)))  # noqa: E731
    llr = {}
    for t in terms:
        having = [c for c in known if t in c["symptoms"]]
        n = len(having)
        llr[t] = {
            d: round(
                logit((sum(d in c["dosha_components"] for c in having) + m * base[d]) / (n + m))
                - logit(base[d]),
                4,
            )
            for d in normalize.DOSHAS
        }
    return {"base_rate": base, "llr": llr, "pseudo_count": m}


def write_pack(
    out_dir: Path,
    conditions: list[dict],
    symptoms: dict,
    prakriti: dict,
    vikriti: dict,
    sources: dict[str, str],
    metrics: dict,
    evidence: dict | None = None,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    hashes = {
        "conditions.json": _write(out_dir / "conditions.json", conditions),
        "symptoms.json": _write(out_dir / "symptoms.json", symptoms),
        "prakriti.json": _write(out_dir / "prakriti.json", prakriti),
        "vikriti.json": _write(out_dir / "vikriti.json", vikriti),
    }
    if evidence is not None:
        hashes["evidence.json"] = _write(out_dir / "evidence.json", evidence)
    content_id = hashlib.sha256("".join(sorted(hashes.values())).encode()).hexdigest()[:12]
    manifest = {
        "pack_version": PACK_VERSION,
        "content_id": content_id,
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source_sha256": sources,
        "files": hashes,
        "counts": {
            "conditions": len(conditions),
            "symptoms": len(symptoms["terms"]),
            "prakriti_questions": len(prakriti["questions"]),
        },
        "metrics": metrics,
    }
    _write(out_dir / "manifest.json", manifest)
    return manifest


# --- loading ----------------------------------------------------------------------------
@dataclass
class KnowledgePack:
    manifest: dict
    conditions: list[dict]
    symptoms: list[dict]
    prakriti: dict
    vikriti: dict
    evidence: dict = field(default_factory=dict)

    @classmethod
    def load(cls, directory: Path) -> KnowledgePack:
        read = lambda n: json.loads((directory / n).read_text(encoding="utf-8"))  # noqa: E731
        evidence = read("evidence.json") if (directory / "evidence.json").exists() else {}
        return cls(
            read("manifest.json"),
            read("conditions.json"),
            read("symptoms.json")["terms"],
            read("prakriti.json"),
            read("vikriti.json"),
            evidence,
        )

    @property
    def version(self) -> str:
        return self.manifest["content_id"]
