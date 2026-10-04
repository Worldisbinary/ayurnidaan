"""Screening-feature selection: which questions should an AI-assisted screener ask?

Two problems, one method family (information-theoretic forward selection):

**A. Questionnaire reduction (Prakriti assessment).** The 25-item questionnaire is
ranked by the JMI criterion (Brown et al., 2012, "Conditional likelihood maximisation"):
    J(f) = sum_{s in S} I(X_f, X_s ; Y)
which rewards items that are informative *jointly* with those already chosen, so
redundant items are skipped. Ranking happens inside each CV training fold (no
selection leakage); the shortest questionnaire within one standard error of the best
CV accuracy is recommended (1-SE rule).

**B. Triage symptom selection (condition knowledge base).** Which symptoms best
discriminate body systems? JMI is compared with a *cluster-guided* strategy - take the
most informative symptom from each symptom cluster in turn - plus frequency and
random baselines. Cluster-guided selection guarantees every symptom cluster has a
probe question, which is what makes the clusters useful for screening design.

**C. Adaptive screener.** At run time, the next question is the one with the highest
expected information gain about the body system given the answers so far.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import RepeatedStratifiedKFold, StratifiedKFold
from sklearn.naive_bayes import BernoulliNB
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder

from ..quality import mutual_information


def _codes(df: pd.DataFrame) -> np.ndarray:
    return np.column_stack([pd.factorize(df[c].astype(str))[0] for c in df.columns])


def jmi_rank(x: np.ndarray, y: np.ndarray, k: int | None = None) -> list[int]:
    """Greedy JMI forward selection over integer-coded discrete features."""
    n_feat = x.shape[1]
    k = n_feat if k is None else min(k, n_feat)
    relevance = np.array([mutual_information(x[:, j], y) for j in range(n_feat)])
    selected = [int(relevance.argmax())]
    score = np.zeros(n_feat)
    cards = x.max(0) + 1
    while len(selected) < k:
        s = selected[-1]
        for f in range(n_feat):
            if f not in selected:
                score[f] += mutual_information(x[:, f] * cards[s] + x[:, s], y)
        score[selected] = -np.inf
        selected.append(int(score.argmax()))
    return selected


# --- A. Questionnaire reduction ---------------------------------------------------------
@dataclass
class QuestionnaireReduction:
    items: list[str]
    ranking: list[str]
    curve: pd.DataFrame  # k, mean_accuracy, se, mean_macro_f1, random_mean_accuracy
    recommended_k: int
    full_accuracy: float
    recommended_accuracy: float
    noise_items: list[str] = field(default_factory=list)


def _clf():
    return make_pipeline(OneHotEncoder(handle_unknown="ignore"), LogisticRegression(max_iter=2000))


def reduce_questionnaire(
    df: pd.DataFrame, label: str, n_splits: int = 5, n_repeats: int = 2, seed: int = 42
) -> QuestionnaireReduction:
    from sklearn.metrics import accuracy_score, f1_score

    items = [c for c in df.columns if c != label]
    x_df = df[items].astype(str)
    x = _codes(x_df)
    y = pd.factorize(df[label])[0]
    rng = np.random.default_rng(seed)
    cv = RepeatedStratifiedKFold(n_splits=n_splits, n_repeats=n_repeats, random_state=seed)
    acc = np.zeros((cv.get_n_splits(), len(items)))
    f1 = np.zeros_like(acc)
    rand = np.zeros_like(acc)
    for fold, (tr, te) in enumerate(cv.split(x, y)):
        order = jmi_rank(x[tr], y[tr])
        rorder = rng.permutation(len(items))
        for k in range(1, len(items) + 1):
            cols = [items[j] for j in order[:k]]
            pred = _clf().fit(x_df.iloc[tr][cols], y[tr]).predict(x_df.iloc[te][cols])
            acc[fold, k - 1] = accuracy_score(y[te], pred)
            f1[fold, k - 1] = f1_score(y[te], pred, average="macro")
            rcols = [items[j] for j in rorder[:k]]
            rpred = _clf().fit(x_df.iloc[tr][rcols], y[tr]).predict(x_df.iloc[te][rcols])
            rand[fold, k - 1] = accuracy_score(y[te], rpred)
    mean, se = acc.mean(0), acc.std(0, ddof=1) / np.sqrt(acc.shape[0])
    best = int(mean.argmax())
    rec_k = int(np.argmax(mean >= mean[best] - se[best])) + 1
    curve = pd.DataFrame(
        {
            "k": np.arange(1, len(items) + 1),
            "mean_accuracy": mean,
            "se": se,
            "mean_macro_f1": f1.mean(0),
            "random_mean_accuracy": rand.mean(0),
        }
    )
    ranking = [items[j] for j in jmi_rank(x, y)]
    return QuestionnaireReduction(
        items=items,
        ranking=ranking,
        curve=curve,
        recommended_k=rec_k,
        full_accuracy=float(mean[-1]),
        recommended_accuracy=float(mean[rec_k - 1]),
    )


# --- B. Triage symptom selection --------------------------------------------------------
def cluster_guided_rank(x: np.ndarray, y: np.ndarray, clusters: np.ndarray) -> list[int]:
    """Round-robin over symptom clusters (largest first), most informative symptom first."""
    relevance = np.array([mutual_information(x[:, j], y) for j in range(x.shape[1])])
    queues = []
    for c in pd.Series(clusters[clusters >= 0]).value_counts().index:
        members = np.where(clusters == c)[0]
        queues.append(list(members[np.argsort(-relevance[members])]))
    unclustered = np.where(clusters < 0)[0]
    order: list[int] = []
    while any(queues):
        for q in queues:
            if q:
                order.append(int(q.pop(0)))
    order += [int(j) for j in unclustered[np.argsort(-relevance[unclustered])]]
    return order


def topk_accuracy(proba: np.ndarray, y: np.ndarray, k: int = 3) -> float:
    top = np.argsort(-proba, axis=1)[:, :k]
    return float((top == y[:, None]).any(1).mean())


def compare_triage_strategies(
    x: np.ndarray,
    y: np.ndarray,
    clusters: np.ndarray,
    budgets: tuple[int, ...],
    n_splits: int = 5,
    seed: int = 42,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    rows = []
    for tr, te in cv.split(x, y):
        orders = {
            "jmi": jmi_rank(x[tr], y[tr], k=max(budgets)),
            "cluster_guided": cluster_guided_rank(x[tr], y[tr], clusters),
            "frequency": list(np.argsort(-x[tr].sum(0))),
            "random": list(rng.permutation(x.shape[1])),
        }
        for name, order in orders.items():
            for b in budgets:
                cols = order[:b]
                nb = BernoulliNB(alpha=1.0).fit(x[tr][:, cols], y[tr])
                proba = np.zeros((len(te), len(np.unique(y))))
                proba[:, nb.classes_] = nb.predict_proba(x[te][:, cols])
                rows.append(
                    {
                        "strategy": name,
                        "budget": b,
                        "top1": topk_accuracy(proba, y[te], 1),
                        "top3": topk_accuracy(proba, y[te], 3),
                    }
                )
    return pd.DataFrame(rows).groupby(["strategy", "budget"], as_index=False).mean()


# --- C. Adaptive screener ---------------------------------------------------------------
def _entropy(p: np.ndarray) -> float:
    p = p[p > 0]
    return float(-(p * np.log2(p)).sum())


@dataclass
class AdaptiveScreener:
    """Bernoulli naive-Bayes posterior over body systems + expected-information-gain policy.

    Knowledge-base profiles list *typical* symptoms; an unlisted symptom is weak evidence
    of absence. Laplace smoothing (alpha) keeps a "no" answer from vetoing a system.
    """

    symptoms: list[str]
    classes: list[str]
    log_prior: np.ndarray
    theta: np.ndarray  # P(symptom present | class), shape (C, S)
    question_pool: list[str]

    @classmethod
    def fit(
        cls,
        x: np.ndarray,
        y_labels: pd.Series,
        symptoms: list[str],
        pool: list[str],
        alpha: float = 1.0,
    ) -> AdaptiveScreener:
        classes = sorted(y_labels.unique())
        y = y_labels.map({c: i for i, c in enumerate(classes)}).to_numpy()
        counts = np.array([x[y == i].sum(0) for i in range(len(classes))])
        n_c = np.bincount(y, minlength=len(classes))
        theta = (counts + alpha) / (n_c[:, None] + 2 * alpha)
        return cls(symptoms, classes, np.log(n_c / n_c.sum()), theta, pool)

    def posterior(self, answers: dict[str, bool]) -> np.ndarray:
        idx = {s: i for i, s in enumerate(self.symptoms)}
        logp = self.log_prior.copy()
        for s, present in answers.items():
            if s in idx:
                t = self.theta[:, idx[s]]
                logp += np.log(t if present else 1 - t)
        p = np.exp(logp - logp.max())
        return p / p.sum()

    def next_question(self, answers: dict[str, bool]) -> tuple[str | None, float]:
        post = self.posterior(answers)
        h0 = _entropy(post)
        idx = {s: i for i, s in enumerate(self.symptoms)}
        best, best_gain = None, 0.0
        for s in self.question_pool:
            if s in answers:
                continue
            t = self.theta[:, idx[s]]
            p_yes = float(post @ t)
            post_yes = post * t / max(p_yes, 1e-12)
            post_no = post * (1 - t) / max(1 - p_yes, 1e-12)
            gain = h0 - (p_yes * _entropy(post_yes) + (1 - p_yes) * _entropy(post_no))
            if gain > best_gain:
                best, best_gain = s, gain
        return best, best_gain

    def top_systems(self, answers: dict[str, bool], n: int = 5) -> list[tuple[str, float]]:
        post = self.posterior(answers)
        order = np.argsort(-post)[:n]
        return [(self.classes[i], float(post[i])) for i in order]
