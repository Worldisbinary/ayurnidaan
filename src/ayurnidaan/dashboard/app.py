"""Clinician dashboard (Streamlit). Run: ``ayur dashboard``.

One screen replaces the three separate source reports: dosha is the conformed
dimension tying patient prevalence, constitution assessments and condition burden
together. All numbers come from ``AnalyticsService`` - the same layer the API uses.

Colours follow the validated reference palette (dataviz skill): dosha identity uses
categorical slots 1-3 (validated all-pairs), magnitude uses the sequential blue ramp,
polarity (odds ratios, reason codes) uses the blue<->red diverging pair with a grey
midpoint. Pass/fail always carries an icon + label, never colour alone.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ayurnidaan.service import AnalyticsService, ArtifactsMissing

DOSHA_COLORS = {"vata": "#2a78d6", "pitta": "#eb6834", "kapha": "#1baf7a"}
SEQ_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
DIVERGING = [[0.0, "#2a78d6"], [0.5, "#f0efec"], [1.0, "#e34948"]]
INK_MUTED = "#8a8984"

st.set_page_config(page_title="Ayurnidaan Analytics", page_icon="🌿", layout="wide")


@st.cache_resource
def service() -> AnalyticsService:
    return AnalyticsService()


def style(fig: go.Figure, height: int = 360, **layout) -> go.Figure:
    fig.update_layout(
        height=height,
        margin={"l": 10, "r": 10, "t": 30, "b": 10},
        font={"size": 13},
        hoverlabel={"font_size": 13},
        **layout,
    )
    fig.update_xaxes(showgrid=False, zeroline=False, linecolor="rgba(128,128,128,.4)")
    fig.update_yaxes(gridcolor="rgba(128,128,128,.15)", zeroline=False)
    return fig


def tile(col, label: str, value, note: str | None = None) -> None:
    """Stat tile; the note is context, not a change, so no delta arrow."""
    col.metric(label, value)
    if note:
        col.caption(note)


def show(fig: go.Figure) -> None:
    st.plotly_chart(fig, width="stretch", theme="streamlit")


try:
    svc = service()
    kpi = svc.kpis()
except ArtifactsMissing as exc:
    st.error(f"No pipeline output yet: {exc}")
    st.stop()

st.title("Ayurnidaan Analytics")
st.caption(
    f"Pipeline run `{kpi['run_id']}` · {kpi['sources_admitted']} sources admitted, "
    f"{kpi['sources_rejected']} rejected by the quality gate"
)

tabs = st.tabs(
    [
        "Overview",
        "Symptom clusters",
        "Screening",
        "Predictive variables",
        "Risk triage",
        "Data quality",
    ]
)

# --- Overview ----------------------------------------------------------------------------
with tabs[0]:
    c = st.columns(6)
    tile(c[0], "Patients", f"{kpi['patients']:,}", "lifestyle intake records")
    tile(c[1], "Prakriti assessments", f"{kpi['assessments']:,}", "25-item questionnaire")
    tile(c[2], "Conditions", f"{kpi['conditions']:,}", f"{kpi['namc_coded_conditions']} NAMC-coded")
    tile(c[3], "Symptom clusters", kpi["symptom_clusters"], f"{kpi['symptoms']} canonical symptoms")
    tile(c[4], "Screening items", kpi["questionnaire_items"], "reduced vs full questionnaire")
    tile(c[5], "Risk model AUC", f"{kpi['risk_model_auc']:.3f}", "untouched holdout")

    st.subheader("Integrated view by dosha")
    st.caption(
        "Three sources with no shared patient keys, joined on the conformed dosha dimension."
    )
    ov = pd.DataFrame(svc.dosha_overview())
    left, right = st.columns([3, 2])
    with left:
        single = ov[ov["dosha"].isin(DOSHA_COLORS)]
        fig = go.Figure(
            go.Bar(
                x=single["dosha"].str.title(),
                y=single["diabetes_prevalence"] * 100,
                marker_color=[DOSHA_COLORS[d] for d in single["dosha"]],
                marker_cornerradius=4,
                width=0.5,
                text=[f"{v:.1f}%" for v in single["diabetes_prevalence"] * 100],
                textposition="outside",
                hovertemplate="%{x}: %{y:.1f}% diabetic<extra></extra>",
            )
        )
        show(
            style(
                fig,
                title="Diabetes prevalence in patient cohort (single-dosha prakriti)",
                yaxis_title="% with diabetes",
                yaxis_range=[0, 100],
                showlegend=False,
            )
        )
    with right:
        table = ov.rename(
            columns={
                "dosha": "Dosha",
                "patients": "Patients",
                "diabetes_prevalence": "Diabetes %",
                "mean_age": "Mean age",
                "assessments": "Assessments",
                "conditions": "KB conditions",
                "share_difficult_prognosis": "Difficult prognosis %",
            }
        )
        table["Diabetes %"] = (table["Diabetes %"] * 100).round(1)
        table["Difficult prognosis %"] = (table["Difficult prognosis %"] * 100).round(1)
        table["Mean age"] = table["Mean age"].round(1)
        for col in ("Patients", "Assessments", "KB conditions"):
            table[col] = table[col].astype("Int64")  # counts, not floats
        table = table.drop(columns=["components"]).astype(object)
        st.dataframe(table.where(table.notna(), "—"), hide_index=True, width="stretch")

# --- Symptom clusters --------------------------------------------------------------------
with tabs[1]:
    cl = svc.clusters
    m = st.columns(4)
    tile(m[0], "Conditions clustered", f"{cl['n_conditions_clustered']:,} / {cl['n_conditions']:,}")
    tile(
        m[1],
        "Symptom variants → canonical",
        f"{cl['raw_symptom_variants']:,} → {cl['n_symptoms']}",
        f"{cl['mention_coverage']:.0%} of mentions retained",
    )
    tile(
        m[2],
        "Body-system NMI",
        f"{cl['nmi_body_system']:.3f}",
        f"chance level {cl['nmi_null_mean']:.3f} · permutation p = {cl['nmi_p_value']:.3f}",
    )
    tile(m[3], "Modularity", f"{cl['modularity']:.2f}", f"Louvain resolution {cl['resolution']}")

    enr = pd.DataFrame(cl["dosha_enrichment"])
    labels = {c_["cluster_id"]: c_["label"] for c_ in cl["clusters"]}
    enr = enr[enr["n_conditions_with_dosha"] >= 10].copy()
    enr["label"] = enr["primary_cluster"].map(labels)
    doshas = ["vata", "pitta", "kapha"]
    z = np.log2(enr[[f"lift_{d}" for d in doshas]].clip(lower=0.125).to_numpy())
    sig = enr[[f"q_{d}" for d in doshas]].to_numpy() < 0.05
    text = [
        [f"{2**v:.2f}×{' *' if s else ''}" for v, s in zip(row, srow, strict=True)]
        for row, srow in zip(z, sig, strict=True)
    ]
    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=[d.title() for d in doshas],
            y=enr["label"],
            colorscale=DIVERGING,
            zmid=0,
            zmin=-2,
            zmax=2,
            text=text,
            texttemplate="%{text}",
            xgap=2,
            ygap=2,
            colorbar={"title": "log₂ lift", "thickness": 10},
            hovertemplate="%{y}<br>%{x}: %{text}<extra></extra>",
        )
    )
    show(
        style(
            fig,
            height=40 + 34 * len(enr),
            title="Dosha enrichment of symptom clusters (* = FDR q < 0.05, clusters with ≥10 conditions)",
            yaxis_autorange="reversed",
        )
    )
    st.caption(
        "Clusters were built from symptom co-occurrence alone - dosha labels were never used. "
        "Red = dosha over-represented among the cluster's conditions; blue = under-represented."
    )

    pick = st.selectbox(
        "Inspect a cluster",
        options=[c_["cluster_id"] for c_ in cl["clusters"]],
        format_func=lambda i: f"{i}: {labels[i]}",
    )
    detail = svc.cluster_detail(pick)
    a, b = st.columns([1, 2])
    a.markdown(
        f"**Consensus cohesion:** {detail['consensus']:.2f}  \n"
        f"**Conditions:** {detail['n_conditions']}"
    )
    a.write(", ".join(detail["symptoms"]))
    b.dataframe(pd.DataFrame(detail["example_conditions"]), hide_index=True, width="stretch")

    with st.expander("Resolution sweep (model selection)"):
        st.dataframe(pd.DataFrame(cl["sweep"]), hide_index=True)

# --- Screening ---------------------------------------------------------------------------
with tabs[2]:
    sc = svc.screening
    q = sc["questionnaire"]
    st.subheader("Prakriti questionnaire reduction")
    st.markdown(
        f"**{q['recommended_k']} of {q['n_items']} items** reach "
        f"**{q['recommended_accuracy']:.1%}** cross-validated accuracy vs **{q['full_accuracy']:.1%}** "
        "with the full questionnaire (1-SE rule, JMI ranking inside each fold)."
    )
    curve = pd.DataFrame(q["curve"])
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=curve["k"],
            y=curve["mean_accuracy"] * 100,
            name="JMI-ranked items",
            mode="lines+markers",
            line={"width": 2, "color": "#2a78d6"},
            marker={"size": 8},
            error_y={"type": "data", "array": curve["se"] * 196, "thickness": 1, "width": 0},
            hovertemplate="%{x} items: %{y:.1f}%<extra>JMI</extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=curve["k"],
            y=curve["random_mean_accuracy"] * 100,
            name="Random item order",
            mode="lines+markers",
            line={"width": 2, "color": "#eb6834"},
            marker={"size": 8},
            hovertemplate="%{x} items: %{y:.1f}%<extra>Random</extra>",
        )
    )
    fig.add_vline(
        x=q["recommended_k"],
        line_dash="dot",
        line_color=INK_MUTED,
        annotation_text=f"recommended: {q['recommended_k']}",
        annotation_position="bottom right",
    )
    show(
        style(
            fig,
            xaxis_title="Questionnaire items",
            yaxis_title="CV accuracy (%)",
            legend={"orientation": "h", "y": -0.25, "yanchor": "top"},
        )
    )
    st.write("Recommended items:", ", ".join(i.replace("_", " ") for i in q["recommended_items"]))
    overlap = set(q["recommended_items"]) & (
        set(q["ranking"]) - set(q["noise_items_from_quality_gate"])
    )
    st.caption(
        f"{len(overlap)} of the {q['recommended_k']} selected items are exactly the items the "
        "quality gate's permutation test found to carry signal - two independent methods agree."
    )

    st.subheader("Triage symptom selection")
    tri = pd.DataFrame(sc["triage"]["results"])
    order = ["jmi", "cluster_guided", "frequency", "random"]
    colors = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
    fig = go.Figure()
    for name, col in zip(order, colors, strict=True):
        d = tri[tri["strategy"] == name]
        fig.add_trace(
            go.Scatter(
                x=d["budget"],
                y=d["top3"] * 100,
                name=name.replace("_", "-"),
                mode="lines+markers",
                line={"width": 2, "color": col},
                marker={"size": 8},
                hovertemplate="%{x} questions: %{y:.1f}%<extra>" + name + "</extra>",
            )
        )
    show(
        style(
            fig,
            title=f"Top-3 body-system accuracy ({sc['triage']['n_conditions']} conditions, "
            f"{sc['triage']['n_systems']} systems)",
            xaxis_title="Symptom questions asked",
            yaxis_title="Top-3 accuracy (%)",
            legend={"orientation": "h", "y": -0.25, "yanchor": "top"},
        )
    )

    st.subheader("Adaptive screener")
    st.caption(
        "Asks the question with the highest expected information gain about the body system."
    )
    if "answers" not in st.session_state:
        st.session_state.answers = {}
    res = svc.screen_next(st.session_state.answers)
    a, b = st.columns([1, 1])
    with a:
        if res["next_question"] and not res["done"]:
            qtext = res["next_question"]
            st.markdown(
                f"**Does the patient have _{qtext}_?**  "
                f"(expected gain {res['expected_information_gain_bits']:.3f} bits)"
            )
            y, n_, r = st.columns(3)
            if y.button("Yes", width="stretch"):
                st.session_state.answers[qtext] = True
                st.rerun()
            if n_.button("No", width="stretch"):
                st.session_state.answers[qtext] = False
                st.rerun()
        else:
            st.success("✅ Screening complete")
        if st.button("Restart"):
            st.session_state.answers = {}
            st.rerun()
        st.write({k: ("yes" if v else "no") for k, v in st.session_state.answers.items()})
    with b:
        post = pd.DataFrame(res["top_body_systems"])
        fig = go.Figure(
            go.Bar(
                x=post["probability"] * 100,
                y=post["body_system"],
                orientation="h",
                marker_color="#2a78d6",
                marker_cornerradius=4,
                text=[f"{p:.0%}" for p in post["probability"]],
                textposition="outside",
                hovertemplate="%{y}: %{x:.1f}%<extra></extra>",
            )
        )
        show(
            style(
                fig,
                height=260,
                title="Posterior over body systems",
                xaxis_range=[0, 110],
                yaxis_autorange="reversed",
                showlegend=False,
            )
        )
        if res["matching_conditions"]:
            st.dataframe(pd.DataFrame(res["matching_conditions"]), hide_index=True, width="stretch")

# --- Predictive variables ----------------------------------------------------------------
with tabs[3]:
    v = svc.variables
    st.markdown(
        f"Training split: **{v['n']:,} patients**, diabetes prevalence {v['prevalence']:.1%} "
        f"({v['excluded_declined_outcome']} cohort respondents declined to answer and are excluded). "
        f"**Confirmed** (3/3 tests): {', '.join(v['confirmed'])}. "
        f"**Supported** (2/3): {', '.join(v['supported']) or '-'}."
    )
    tbl = pd.DataFrame(v["table"])
    tier_icon = {
        "confirmed": "✅ confirmed",
        "supported": "◐ supported",
        "not supported": "— not supported",
    }
    tbl["evidence"] = tbl["evidence_tier"].map(tier_icon)
    st.dataframe(
        tbl[
            [
                "consensus_rank",
                "variable",
                "evidence",
                "effect",
                "effect_measure",
                "q_value",
                "lrt_q",
                "stability",
                "perm_auc_drop",
                "perm_ci_low",
                "perm_ci_high",
            ]
        ].round(4),
        hide_index=True,
        width="stretch",
    )
    ors = pd.DataFrame(v["odds_ratios"]).sort_values("odds_ratio")
    fig = go.Figure(
        go.Scatter(
            x=ors["odds_ratio"],
            y=ors["term"],
            mode="markers",
            marker={
                "size": 9,
                "color": "#2a78d6",
                "line": {"width": 2, "color": "rgba(255,255,255,.9)"},
            },
            error_x={
                "type": "data",
                "symmetric": False,
                "array": ors["ci_high"] - ors["odds_ratio"],
                "arrayminus": ors["odds_ratio"] - ors["ci_low"],
                "thickness": 1.5,
                "width": 0,
                "color": INK_MUTED,
            },
            customdata=ors[["ci_low", "ci_high", "p_value"]],
            hovertemplate="%{y}<br>OR %{x:.2f} [%{customdata[0]:.2f}, %{customdata[1]:.2f}]"
            "<br>p = %{customdata[2]:.3g}<extra></extra>",
        )
    )
    fig.add_vline(x=1, line_color=INK_MUTED, line_width=1)
    refs = ", ".join(f"{k} = {r}" for k, r in v["reference_levels"].items())
    show(
        style(
            fig,
            height=30 + 22 * len(ors),
            xaxis_type="log",
            xaxis_title="Adjusted odds ratio (log scale)",
            title="Multivariable logistic regression - adjusted odds ratios with 95% CI",
            showlegend=False,
        )
    )
    st.caption(f"Reference levels: {refs}. Age per 10 years.")

# --- Risk triage -------------------------------------------------------------------------
with tabs[4]:
    card = svc.model_card
    h = card["holdout"]
    st.markdown(
        f"Model: **{card['model'].replace('_', ' ')}** on {', '.join(card['features'])}. Holdout AUC "
        f"**{h['auc']:.3f}** (95% CI {h['auc_ci95'][0]:.3f}-{h['auc_ci95'][1]:.3f}), Brier {h['brier']:.3f} "
        f"(no-skill {h['brier_null']:.3f}), calibration slope {h['calibration_slope']:.2f}."
    )
    with st.form("risk"):
        f = st.columns(3)
        age = f[0].number_input("Age", 15, 100, 50)
        fam = f[1].selectbox("Family history of diabetes", ["no", "yes", "unknown"])
        sleep = f[2].slider("Sleep hours / night", 3.0, 12.0, 7.0, 0.5)
        g = st.columns(2)
        dosha = g[0].selectbox(
            "Prakriti",
            [
                "unknown",
                "vata",
                "pitta",
                "kapha",
                "vata-pitta",
                "vata-kapha",
                "pitta-kapha",
                "tridosha",
            ],
        )
        prefs = g[1].multiselect(
            "Food preferences",
            [
                "cooling",
                "dry",
                "heavy",
                "light",
                "oily",
                "pungent",
                "salty",
                "sour",
                "spicy",
                "sweet",
                "warming",
            ],
        )
        submitted = st.form_submit_button("Score")
    if submitted:
        patient = {"age": age, "family_history": fam, "sleep_hours": sleep, "dosha": dosha}
        patient |= {
            f"pref_{p}": float(p in prefs)
            for p in [
                "cooling",
                "dry",
                "heavy",
                "light",
                "oily",
                "pungent",
                "salty",
                "sour",
                "spicy",
                "sweet",
                "warming",
            ]
        }
        out = svc.score_risk(patient)
        a, b = st.columns([1, 2])
        a.metric("Estimated probability", f"{out['probability']:.0%}")
        if out["flag_for_screening"]:
            a.warning(f"⚠️ Flag for screening (threshold {out['threshold']:.2f})")
        else:
            a.success(f"✅ Below screening threshold ({out['threshold']:.2f})")
        a.caption(out["disclaimer"])
        rs = pd.DataFrame(out["reasons"]).iloc[::-1]
        fig = go.Figure(
            go.Bar(
                x=rs["log_odds"],
                y=[f"{r.variable} = {r.value}" for r in rs.itertuples()],
                orientation="h",
                marker_color=["#e34948" if x > 0 else "#2a78d6" for x in rs["log_odds"]],
                marker_cornerradius=4,
                customdata=rs[["direction", "typical_value"]],
                hovertemplate="%{y}<br>%{x:+.3f} log-odds (%{customdata[0]})"
                "<br>typical: %{customdata[1]}<extra></extra>",
            )
        )
        fig.add_vline(x=0, line_color=INK_MUTED, line_width=1)
        b.plotly_chart(
            style(
                fig,
                height=280,
                title="Why: change in log-odds vs a typical patient",
                showlegend=False,
            ),
            width="stretch",
            theme="streamlit",
        )
    st.subheader("Subgroup performance")
    st.dataframe(pd.DataFrame(card["subgroups"]).T.round(3), width="stretch")
    for lim in card["limitations"]:
        st.markdown(f"- {lim}")

# --- Data quality ------------------------------------------------------------------------
with tabs[5]:
    qr = svc.quality
    rows = []
    for name, rep in qr.items():
        failed = [c_["check"] for c_ in rep["checks"] if c_["blocking"] and not c_["passed"]]
        rows.append(
            {
                "source": name,
                "origin": rep["origin"],
                "role": rep["role"],
                "rows": rep["rows"],
                "verdict": "✅ admitted"
                if rep["admitted"]
                else ("⛔ rejected: " + ", ".join(failed) if failed else "— audit only"),
                "noise features": len(rep["noise_features"]),
                "PII columns scrubbed": ", ".join(rep["pii_columns"]) or "-",
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    pick = st.selectbox("Checks for source", list(qr))
    checks = pd.DataFrame(qr[pick]["checks"])
    checks["result"] = np.where(
        checks["passed"], "✅ pass", np.where(checks["blocking"], "⛔ fail", "⚠️ advisory")
    )
    st.dataframe(
        checks[["check", "result", "value", "threshold", "blocking", "detail"]],
        hide_index=True,
        width="stretch",
    )
    if qr[pick]["noise_features"]:
        st.caption(
            "Features with no label signal (permutation MI): "
            + ", ".join(qr[pick]["noise_features"])
        )
