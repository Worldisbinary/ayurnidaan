"""End-to-end pipeline: verify -> audit -> transform -> load -> analyse -> publish.

Each run gets a ``run_id``; lineage (source checksum, rows in/out, admitted?) and every
data-quality check are appended to the warehouse so any dashboard number can be traced
back to exact input bytes and the gate decision that admitted them.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.model_selection import train_test_split

from . import __version__, ingest, quality, warehouse
from .analytics import clusters as clus
from .analytics import risk, screening, variables
from .clinical import knowledge
from .config import Registry, Settings, load_registry
from .logging_utils import get_logger
from .transform import epidemiology, normalize, pii, symptoms, terminology

log = get_logger(__name__)


def _json_default(o):
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return None if np.isnan(o) else float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (pd.Timestamp, datetime)):
        return o.isoformat()
    raise TypeError(type(o))


def environment() -> dict[str, str]:
    """Library versions the pickled artifacts were built with; they only load reliably
    under matching versions, so the service warns on drift."""
    import platform

    import sklearn

    return {
        "python": platform.python_version(),
        "scikit-learn": sklearn.__version__,
        "pandas": pd.__version__,
        "numpy": np.__version__,
        "ayurnidaan": __version__,
    }


def write_json(path: Path, obj) -> None:
    path.write_text(
        json.dumps(obj, indent=2, default=_json_default, allow_nan=False), encoding="utf-8"
    )


@dataclass
class RunContext:
    settings: Settings
    registry: Registry
    run_id: str = field(
        default_factory=lambda: (
            datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
        )
    )
    timings: dict[str, float] = field(default_factory=dict)

    def step(self, name: str):
        ctx = self

        class _Timer:
            def __enter__(self):
                self.t = time.perf_counter()
                log.info("step.start", fields={"run_id": ctx.run_id, "step": name})

            def __exit__(self, *exc):
                ctx.timings[name] = round(time.perf_counter() - self.t, 2)
                log.info(
                    "step.end",
                    fields={"run_id": ctx.run_id, "step": name, "seconds": ctx.timings[name]},
                )

        return _Timer()


# --- transforms ------------------------------------------------------------------------
# Practitioner-only fields (treatment principles, herbs with doses, tests) vs general
# guidance that is safe to show a patient (diet, yoga, prevention - no dosing).
CLASSICAL_REFERENCE = {"treatment_principles": "Treatment Principles", "source_text": "Source Text"}
MODERN_REFERENCE = {
    "tests": "Diagnosis & Tests",
    "severity": "Symptom Severity",
    "herbs": "Ayurvedic Herbs",
    "formulation": "Formulation",
    "complications": "Complications",
    "medical_intervention": "Medical Intervention",
    "risk_factors": "Risk Factors",
}
MODERN_PATIENT_GUIDANCE = {
    "diet_lifestyle": "Diet and Lifestyle Recommendations",
    "yoga": "Yoga & Physical Therapy",
    "prevention": "Prevention",
}


def _col(df: pd.DataFrame, name: str) -> pd.Series | None:
    return df[name] if name in df.columns else None


def _reference(df: pd.DataFrame, fields: dict[str, str]) -> list[str | None]:
    present = {k: v for k, v in fields.items() if v in df.columns}
    if not present:
        return [None] * len(df)
    return [
        json.dumps({k: row[v] for k, v in present.items() if isinstance(row[v], str)})
        for _, row in df.iterrows()
    ]


def build_conditions(
    classical: pd.DataFrame, modern: pd.DataFrame, namc: pd.DataFrame
) -> pd.DataFrame:
    links = terminology.link_namc(classical["Ayurvedic Name"], namc)
    cl = pd.DataFrame(
        {
            "condition_id": [f"CL-{i:04d}" for i in range(1, len(classical) + 1)],
            "source": "condition_kb_classical",
            "name": classical["Ayurvedic Name"],
            "modern_equivalent": classical["Modern Equivalent"],
            "body_system_raw": classical["System / Body Part"],
            "body_system": classical["System / Body Part"].map(normalize.canonical_body_system),
            "dosha": classical["Dosha Predominance"].map(normalize.canonical_dosha),
            "prognosis": classical["Prognosis"].str.casefold().str.strip(),
            "source_text": classical["Source Text"],
            "symptoms_raw": classical["Symptoms"],
            "age_text": _col(classical, "Age Group"),
            "sex_text": _col(classical, "Gender"),
            "practitioner_reference": _reference(classical, CLASSICAL_REFERENCE),
            "patient_guidance": None,
        }
    )
    cl = pd.concat([cl, links.reset_index(drop=True)], axis=1)
    mo = pd.DataFrame(
        {
            "condition_id": [f"MO-{i:04d}" for i in range(1, len(modern) + 1)],
            "source": "condition_kb_modern",
            "name": modern["Disease"],
            "modern_equivalent": modern["Disease"],
            "body_system_raw": None,
            "body_system": "unspecified",
            "dosha": modern["Doshas"].map(normalize.canonical_dosha),
            "prognosis": modern["Prognosis"].str.casefold().str.strip(),
            "source_text": "AyurGenixAI",
            "symptoms_raw": modern["Symptoms"],
            "age_text": _col(modern, "Age Group"),
            "sex_text": _col(modern, "Gender"),
            "practitioner_reference": _reference(modern, MODERN_REFERENCE),
            "patient_guidance": _reference(modern, MODERN_PATIENT_GUIDANCE),
            "namc_code": None,
            "namc_term": None,
            "namc_tier": "not applicable",
            "namc_score": np.nan,
        }
    )
    return pd.concat([cl, mo], ignore_index=True)


def dim_dosha() -> pd.DataFrame:
    codes = ["vata", "pitta", "kapha", "vata-pitta", "vata-kapha", "pitta-kapha", "tridosha"]
    return pd.DataFrame(
        {
            "dosha": codes,
            "components": [", ".join(normalize.dosha_components(c)) for c in codes],
            "sort_order": range(len(codes)),
        }
    )


def cluster_dosha_enrichment(conditions: pd.DataFrame) -> pd.DataFrame:
    """Lift of each dosha component among a cluster's conditions vs all conditions."""
    df = conditions[conditions["primary_cluster"] >= 0].copy()
    for d in normalize.DOSHAS:
        df[d] = df["dosha"].map(lambda c, d=d: d in normalize.dosha_components(c))
    known = df[df["dosha"].notna()]
    base = known[list(normalize.DOSHAS)].mean()
    g = known.groupby("primary_cluster")[list(normalize.DOSHAS)].mean()
    n = known.groupby("primary_cluster").size()
    lift = (g / base).add_prefix("lift_")
    # One-sided Fisher exact test for over-representation, BH-FDR across all cells.
    pvals = {}
    for c in g.index:
        in_c = known["primary_cluster"] == c
        for d in normalize.DOSHAS:
            table = [
                [int((in_c & known[d]).sum()), int((in_c & ~known[d]).sum())],
                [int((~in_c & known[d]).sum()), int((~in_c & ~known[d]).sum())],
            ]
            pvals[(c, d)] = stats.fisher_exact(table, alternative="greater").pvalue
    q = dict(
        zip(pvals, stats.false_discovery_control(list(pvals.values()), method="bh"), strict=True)
    )
    qdf = pd.DataFrame(
        {f"q_{d}": [q[(c, d)] for c in g.index] for d in normalize.DOSHAS}, index=g.index
    )
    out = pd.concat(
        [n.rename("n_conditions_with_dosha"), g.add_prefix("share_"), lift, qdf], axis=1
    )
    return out.reset_index()


# --- main ------------------------------------------------------------------------------
def run(settings: Settings, fast: bool = False) -> dict:
    """Run the full pipeline. ``fast`` trims bootstrap/CV repeats (CI smoke tests)."""
    registry = load_registry(settings.sources_file)
    ctx = RunContext(settings, registry)
    out = settings.artifacts_dir
    out.mkdir(parents=True, exist_ok=True)
    started = datetime.now(UTC)
    seed = settings.seed

    with ctx.step("verify_and_audit"):
        raws, frames, reports = {}, {}, {}
        for name, src in registry.sources.items():
            raws[name] = ingest.verify(src, settings.data_dir)
            frames[name] = ingest.read_raw(raws[name])
            reports[name] = quality.audit(frames[name], src, registry.quality_gate, seed=seed)
        admitted = {n for n, r in reports.items() if r.passed and registry[n].role != "audit_only"}
        required = {n for n, s in registry.sources.items() if s.role != "audit_only"}
        if missing := required - admitted:
            raise RuntimeError(f"Quality gate rejected required sources: {sorted(missing)}")

    with ctx.step("transform"):
        intake_raw = frames["patient_intake"]
        intake = normalize.clean_patient_intake(
            pii.scrub(
                intake_raw,
                reports["patient_intake"].pii_columns,
                settings.pii_salt,
                key_from=["Name", "Age", "Gender"],
            )
        )
        assessments = normalize.clean_prakriti_assessment(frames["prakriti_assessment"])
        conditions = build_conditions(
            frames["condition_kb_classical"],
            frames["condition_kb_modern"],
            frames["namc_terminology"],
        )
        if {"orphanet_prevalence", "orphanet_names"} <= set(frames):
            priors = epidemiology.disorder_priors(frames["orphanet_prevalence"])
            conditions["prevalence"] = epidemiology.link_conditions(
                conditions["name"],
                conditions["modern_equivalent"],
                frames["orphanet_names"],
                priors,
            )
        else:  # registry without epidemiology sources: no prevalence adjustment
            conditions["prevalence"] = None
        n_classical = len(frames["condition_kb_classical"])
        conflict_pos = set(reports["condition_kb_classical"].conflicting_rows) | {
            n_classical + p for p in reports["condition_kb_modern"].conflicting_rows
        }
        conditions["profile_conflict"] = conditions.index.isin(sorted(conflict_pos))
        raw_docs = [symptoms.split_symptoms(s) for s in conditions["symptoms_raw"]]
        vocab = symptoms.SymptomVocabulary().fit(raw_docs)
        docs = [vocab.transform(d) for d in raw_docs]

    with ctx.step("symptom_clustering"):
        has_sym = np.array([bool(d) for d in docs])
        clustering = clus.cluster_symptoms(
            [d for d, h in zip(docs, has_sym, strict=True) if h],
            vocab.terms,
            conditions.loc[has_sym, "body_system"].reset_index(drop=True),
            n_boot=10 if fast else 30,
            seed=seed,
        )
        primary = np.full(len(conditions), -1)
        primary[has_sym] = clustering.condition_cluster
        conditions["primary_cluster"] = primary
        conditions["n_symptoms"] = [len(d) for d in docs]
        sym_table = clustering.symptom_table(vocab.doc_freq)
        sym_table.insert(0, "symptom_id", [f"S-{i:03d}" for i in range(1, len(sym_table) + 1)])
        sid = dict(zip(sym_table["symptom"], sym_table["symptom_id"], strict=True))
        bridge = pd.DataFrame(
            [
                (cid, sid[t])
                for cid, d in zip(conditions["condition_id"], docs, strict=True)
                for t in d
            ],
            columns=["condition_id", "symptom_id"],
        )
        aliases = pd.DataFrame(vocab.aliases(), columns=["variant", "canonical"])
        aliases["method"] = np.where(
            aliases["variant"].isin(vocab.backoff), "head_term_backoff", "merge"
        )
        enrichment = cluster_dosha_enrichment(conditions)

    with ctx.step("screening"):
        qr = screening.reduce_questionnaire(
            assessments.drop(columns=["assessment_id"]),
            "dosha",
            n_repeats=1 if fast else 2,
            seed=seed,
        )
        qr.noise_items = [normalize.snake(c) for c in reports["prakriti_assessment"].noise_features]
        x_all = clus.binary_matrix(docs, vocab.terms).toarray().astype(int)
        lab = conditions["body_system"]
        counts = lab.value_counts()
        tri = (
            ~lab.isin(clus.UNLABELLED_SYSTEMS) & lab.map(counts).ge(15) & (x_all.sum(1) > 0)
        ).to_numpy()
        y_tri = pd.factorize(lab[tri])[0]
        triage = screening.compare_triage_strategies(
            x_all[tri], y_tri, clustering.labels, budgets=(5, 10, 20, 30, 40, 60), seed=seed
        )
        pool_idx = screening.jmi_rank(x_all[tri], y_tri, k=60)
        screener = screening.AdaptiveScreener.fit(
            x_all[tri],
            lab[tri].reset_index(drop=True),
            vocab.terms,
            [vocab.terms[i] for i in pool_idx],
        )

    with ctx.step("variables_and_risk"):
        labelled = intake[intake["diabetes"].notna()]
        train_idx, hold_idx = train_test_split(
            labelled.index,
            test_size=0.2,
            stratify=labelled["diabetes"].astype(int),
            random_state=seed,
        )
        intake["split"] = "unlabelled"
        intake.loc[train_idx, "split"] = "train"
        intake.loc[hold_idx, "split"] = "holdout"
        var_report, hgb_auc = variables.discover(intake.loc[train_idx], seed=seed)
        var_report.excluded_rows = int(intake["diabetes"].isna().sum())  # cohort-wide, not split
        features = var_report.predictive + var_report.supported
        model = risk.train(intake.loc[train_idx], intake.loc[hold_idx], features, seed=seed)

    with ctx.step("knowledge_pack"):
        lit_path = settings.knowledge_dir / "evidence_cache.json"
        literature = json.loads(lit_path.read_text(encoding="utf-8")) if lit_path.exists() else None
        pack_conditions = knowledge.build_conditions(conditions, docs, literature)
        pack_symptoms = knowledge.build_symptoms(vocab, sym_table)
        prakriti_items = qr.ranking[: qr.recommended_k]
        pack_prakriti = knowledge.build_prakriti(assessments, prakriti_items, seed=seed)
        all_items = [c for c in assessments.columns if c not in ("assessment_id", "dosha")]
        pack_prakriti_full = knowledge.build_prakriti(assessments, all_items, seed=seed)
        pack_vikriti = knowledge.build_vikriti(pack_conditions, vocab.terms)
        evidence = knowledge.build_evidence(pack_conditions, literature) if literature else None
        manifest = knowledge.write_pack(
            settings.knowledge_dir,
            pack_conditions,
            pack_symptoms,
            pack_prakriti,
            pack_vikriti,
            sources={n: raws[n].sha256 for n in admitted},
            metrics={
                "prakriti_cv_accuracy": pack_prakriti["cv_accuracy"],
                "cluster_nmi_body_system": clustering.nmi_body_system,
            },
            evidence=evidence,
            prakriti_full=pack_prakriti_full,
        )

    with ctx.step("load_warehouse"), warehouse.connect(settings.warehouse_path) as con:
        warehouse.init(con)
        warehouse.replace_table(con, "dim_dosha", dim_dosha())
        warehouse.replace_table(
            con,
            "dim_body_system",
            conditions.groupby("body_system").size().rename("conditions").reset_index(),
        )
        warehouse.replace_table(con, "dim_symptom", sym_table)
        warehouse.replace_table(con, "symptom_alias", aliases)
        warehouse.replace_table(
            con,
            "dim_condition",
            conditions.drop(columns=["symptoms_raw"]).assign(
                prevalence=conditions["prevalence"].map(lambda v: json.dumps(v) if v else None)
            ),
        )
        warehouse.replace_table(con, "bridge_condition_symptom", bridge)
        warehouse.replace_table(con, "fact_patient_intake", intake)
        warehouse.replace_table(con, "fact_prakriti_assessment", assessments)
        warehouse.create_views(con)
        config_sha = hashlib.sha256(settings.sources_file.read_bytes()).hexdigest()
        warehouse.append(
            con,
            "meta_run",
            pd.DataFrame(
                [
                    {
                        "run_id": ctx.run_id,
                        "started_at": started.replace(tzinfo=None),
                        "finished_at": datetime.now(UTC).replace(tzinfo=None),
                        "status": "success",
                        "code_version": __version__,
                        "config_sha256": config_sha,
                    }
                ]
            ),
        )
        rows_out = {
            "patient_intake": len(intake),
            "prakriti_assessment": len(assessments),
            "condition_kb_classical": int((conditions["source"] == "condition_kb_classical").sum()),
            "condition_kb_modern": int((conditions["source"] == "condition_kb_modern").sum()),
            "namc_terminology": len(frames["namc_terminology"]),
        }
        warehouse.append(
            con,
            "meta_lineage",
            pd.DataFrame(
                [
                    {
                        "run_id": ctx.run_id,
                        "source": n,
                        "origin": registry[n].origin,
                        "sha256": raws[n].sha256,
                        "rows_in": len(frames[n]),
                        "rows_out": rows_out.get(n, 0),
                        "admitted": n in admitted,
                    }
                    for n in registry.sources
                ]
            ),
        )
        warehouse.append(
            con,
            "dq_check",
            pd.DataFrame(
                [
                    {
                        "run_id": ctx.run_id,
                        "source": n,
                        "check_name": c.check,
                        "value": c.value,
                        "threshold": c.threshold,
                        "passed": c.passed,
                        "blocking": c.blocking,
                        "detail": c.detail,
                    }
                    for n, r in reports.items()
                    for c in r.checks
                ]
            ),
        )

    with ctx.step("publish_artifacts"):
        quality_doc = {
            n: r.to_dict()
            | {
                "admitted": n in admitted,
                "description": registry[n].description,
                "origin": registry[n].origin,
            }
            for n, r in reports.items()
        }
        write_json(out / "quality_report.json", quality_doc)
        write_json(
            out / "clusters.json",
            {
                "n_conditions": len(conditions),
                "n_conditions_clustered": int((primary >= 0).sum()),
                "n_symptoms": len(vocab.terms),
                "raw_symptom_variants": len({t for d in raw_docs for t in d}),
                "mention_coverage": vocab.coverage(raw_docs),
                "resolution": clustering.resolution,
                "stability_ari": clustering.stability,
                "modularity": clustering.modularity,
                "nmi_body_system": clustering.nmi_body_system,
                "nmi_null_mean": clustering.nmi_null_mean,
                "nmi_p_value": clustering.nmi_p_value,
                "sweep": clustering.sweep,
                "clusters": [
                    {
                        "cluster_id": c,
                        "label": clustering.cluster_names[c],
                        "consensus": clustering.cluster_stability.get(c),
                        "symptoms": sym_table.loc[sym_table["cluster_id"] == c]
                        .sort_values("doc_freq", ascending=False)["symptom"]
                        .tolist(),
                        "n_conditions": int((primary == c).sum()),
                    }
                    for c in range(int(clustering.labels.max()) + 1)
                ],
                "dosha_enrichment": enrichment.to_dict("records"),
                "edges": [{"source": a, "target": b, "npmi": w} for a, b, w in clustering.edges],
            },
        )
        write_json(
            out / "screening.json",
            {
                "questionnaire": {
                    "n_items": len(qr.items),
                    "recommended_k": qr.recommended_k,
                    "recommended_items": qr.ranking[: qr.recommended_k],
                    "ranking": qr.ranking,
                    "full_accuracy": qr.full_accuracy,
                    "recommended_accuracy": qr.recommended_accuracy,
                    "noise_items_from_quality_gate": qr.noise_items,
                    "curve": qr.curve.to_dict("records"),
                },
                "triage": {
                    "n_conditions": int(tri.sum()),
                    "n_systems": len(np.unique(y_tri)),
                    "results": triage.to_dict("records"),
                },
                "screener_pool": screener.question_pool,
            },
        )
        write_json(
            out / "variables.json",
            {
                "n": var_report.n,
                "prevalence": var_report.prevalence,
                "excluded_declined_outcome": var_report.excluded_rows,
                "hgb_oof_auc": hgb_auc,
                "confirmed": var_report.predictive,
                "supported": var_report.supported,
                "reference_levels": var_report.reference_levels,
                "table": var_report.table.to_dict("records"),
                "odds_ratios": var_report.odds_ratios.to_dict("records"),
            },
        )
        write_json(
            out / "model_card.json",
            model.card
            | {"run_id": ctx.run_id, "threshold": model.threshold, "environment": environment()},
        )
        joblib.dump(model, out / "risk_model.joblib")
        joblib.dump(screener, out / "screener.joblib")
        summary = {
            "run_id": ctx.run_id,
            "timings": ctx.timings,
            "admitted": sorted(admitted),
            "rejected": sorted(n for n, r in reports.items() if not r.passed),
            "knowledge_pack": manifest["content_id"],
        }
        write_json(out / "run_summary.json", summary)
    log.info("run.complete", fields=summary)
    return summary
