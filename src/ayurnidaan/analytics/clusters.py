"""Symptom clustering via consensus community detection on an NPMI co-occurrence graph.

1. Conditions x symptoms binary matrix (canonical vocabulary).
2. Edge weight = normalised PMI of two symptoms co-occurring in a condition profile;
   NPMI corrects raw co-counts for symptom frequency ("fever" co-occurs with
   everything, which says nothing).
3. Louvain community detection on B bootstrap resamples of the conditions.
4. Consensus matrix M[i, j] = share of resamples in which i and j share a community;
   final clusters = average-linkage cut of (1 - M) at 0.5, i.e. symptoms that are
   co-assigned in the majority of resamples. Singletons are left unclustered.
5. Resolution is swept and chosen by bootstrap stability (mean ARI vs consensus),
   so the clustering is reproducible rather than an artefact of one random seed.
6. External validity: do symptom clusters recover body systems better than chance?
   NMI(condition cluster, body system) is compared to a permutation null, using only
   conditions whose source records a body system.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx
import numpy as np
import pandas as pd
from scipy import sparse
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score

UNLABELLED_SYSTEMS = frozenset({"unspecified", "other"})


def binary_matrix(docs: list[list[str]], vocab: list[str]) -> sparse.csr_matrix:
    index = {t: i for i, t in enumerate(vocab)}
    rows, cols = [], []
    for r, doc in enumerate(docs):
        for t in doc:
            if t in index:
                rows.append(r)
                cols.append(index[t])
    data = np.ones(len(rows), dtype=np.float32)
    return sparse.csr_matrix((data, (rows, cols)), shape=(len(docs), len(vocab)))


def npmi(x: sparse.csr_matrix) -> tuple[np.ndarray, np.ndarray]:
    """Return (NPMI matrix, co-occurrence counts). NPMI in [-1, 1]; -1 if never co-occur."""
    n = x.shape[0]
    co = (x.T @ x).toarray()
    df = np.diag(co).copy()
    with np.errstate(divide="ignore", invalid="ignore"):
        p_ij = co / n
        p_i = df / n
        pmi = np.log(p_ij / np.outer(p_i, p_i))
        out = pmi / -np.log(p_ij)
    out[co == 0] = -1.0
    out[~np.isfinite(out)] = 0.0
    np.fill_diagonal(out, 0.0)
    return out, co


def build_graph(x: sparse.csr_matrix, min_co: int, min_npmi: float) -> nx.Graph:
    w, co = npmi(x)
    g = nx.Graph()
    g.add_nodes_from(range(x.shape[1]))
    ii, jj = np.where(np.triu((co >= min_co) & (w >= min_npmi), k=1))
    g.add_weighted_edges_from((int(i), int(j), float(w[i, j])) for i, j in zip(ii, jj, strict=True))
    return g


def louvain_labels(g: nx.Graph, resolution: float, seed: int) -> np.ndarray:
    labels = np.full(g.number_of_nodes(), -1)
    comms = nx.community.louvain_communities(g, weight="weight", resolution=resolution, seed=seed)
    cid = 0
    for comm in sorted(comms, key=lambda c: (-len(c), min(c))):
        if len(comm) > 1:
            labels[list(comm)] = cid
            cid += 1
    return labels


def _ari_on_shared(a: np.ndarray, b: np.ndarray) -> float:
    mask = (a >= 0) & (b >= 0)
    return float(adjusted_rand_score(a[mask], b[mask])) if mask.sum() > 1 else 0.0


@dataclass
class ConsensusRun:
    resolution: float
    labels: np.ndarray
    consensus: np.ndarray
    stability: float
    n_clusters: int
    modularity: float


def consensus_cluster(
    x: sparse.csr_matrix, resolution: float, n_boot: int, min_co: int, min_npmi: float, seed: int
) -> ConsensusRun:
    rng = np.random.default_rng(seed)
    n, m = x.shape
    together = np.zeros((m, m))
    both = np.zeros((m, m))
    partitions = []
    for b in range(n_boot):
        xb = x[rng.integers(0, n, n)]
        lab = louvain_labels(build_graph(xb, min_co, min_npmi), resolution, seed + b)
        partitions.append(lab)
        present = lab >= 0
        both += np.outer(present, present)
        together += (lab[:, None] == lab[None, :]) & np.outer(present, present)
    with np.errstate(invalid="ignore", divide="ignore"):
        cons = np.where(both > 0, together / both, 0.0)
    np.fill_diagonal(cons, 1.0)

    clustered = np.where(np.diag(both) >= n_boot / 2)[0]  # in a community in most resamples
    labels = np.full(m, -1)
    if len(clustered) > 1:
        dist = squareform(1.0 - cons[np.ix_(clustered, clustered)], checks=False)
        raw = fcluster(linkage(dist, method="average"), t=0.5, criterion="distance")
        sizes = pd.Series(raw).value_counts()
        keep = sizes[sizes > 1].index
        order = {c: i for i, c in enumerate(sizes.loc[keep].sort_values(ascending=False).index)}
        for node, c in zip(clustered, raw, strict=True):
            if c in order:
                labels[node] = order[c]

    full = build_graph(x, min_co, min_npmi)
    comms = [set(np.where(labels == c)[0]) for c in range(labels.max() + 1)]
    rest = set(full.nodes) - set().union(*comms) if comms else set(full.nodes)
    mod = (
        nx.community.modularity(full, [*comms, *({r} for r in rest)], weight="weight")
        if comms
        else 0.0
    )
    stability = float(np.mean([_ari_on_shared(p, labels) for p in partitions]))
    return ConsensusRun(resolution, labels, cons, stability, int(labels.max() + 1), float(mod))


@dataclass
class SymptomClustering:
    vocab: list[str]
    labels: np.ndarray
    resolution: float
    stability: float
    modularity: float
    sweep: list[dict]
    cluster_stability: dict[int, float]
    cluster_names: dict[int, str]
    condition_cluster: np.ndarray
    nmi_body_system: float
    nmi_null_mean: float
    nmi_p_value: float
    edges: list[tuple[str, str, float]] = field(default_factory=list)

    def symptom_table(self, doc_freq: dict[str, int]) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "symptom": self.vocab,
                "cluster_id": self.labels,
                "cluster_label": [
                    self.cluster_names.get(int(c), "unclustered") for c in self.labels
                ],
                "doc_freq": [doc_freq.get(t, 0) for t in self.vocab],
            }
        )


def assign_conditions(x: sparse.csr_matrix, labels: np.ndarray) -> np.ndarray:
    k = labels.max() + 1
    if k <= 0:
        return np.full(x.shape[0], -1)
    onehot = np.zeros((len(labels), k))
    onehot[labels >= 0, labels[labels >= 0]] = 1
    counts = np.asarray(x @ onehot)
    out = counts.argmax(1)
    out[counts.max(1) == 0] = -1
    return out


def name_clusters(
    x: sparse.csr_matrix, vocab: list[str], labels: np.ndarray, systems: pd.Series, cond: np.ndarray
) -> dict[int, str]:
    g_w, _ = npmi(x)
    names = {}
    for c in range(labels.max() + 1):
        idx = np.where(labels == c)[0]
        # Most central members = highest summed NPMI to the rest of the cluster.
        central = idx[np.argsort(-np.clip(g_w[np.ix_(idx, idx)], 0, None).sum(1))][:3]
        in_c = systems[cond == c]
        sys_counts = in_c[~in_c.isin(UNLABELLED_SYSTEMS)].value_counts()
        top_sys = sys_counts.index[0] if len(sys_counts) else "mixed"
        names[c] = f"{top_sys}: " + ", ".join(vocab[i] for i in central)
    return names


def cluster_symptoms(
    docs: list[list[str]],
    vocab: list[str],
    body_systems: pd.Series,
    resolutions: tuple[float, ...] = (0.3, 0.4, 0.5, 0.6, 0.8, 1.0),
    n_boot: int = 30,
    min_co: int = 2,
    min_npmi: float = 0.25,
    min_clusters: int = 8,
    max_clusters: int = 30,
    seed: int = 42,
) -> SymptomClustering:
    x = binary_matrix(docs, vocab)
    runs = [consensus_cluster(x, r, n_boot, min_co, min_npmi, seed) for r in resolutions]
    eligible = [r for r in runs if min_clusters <= r.n_clusters <= max_clusters] or runs
    best = max(eligible, key=lambda r: (round(r.stability, 3), r.modularity))

    labels = best.labels
    cond = assign_conditions(x, labels)
    sys_arr = body_systems.to_numpy()
    mask = (cond >= 0) & ~np.isin(sys_arr, list(UNLABELLED_SYSTEMS))
    nmi = float(normalized_mutual_info_score(sys_arr[mask], cond[mask]))
    rng = np.random.default_rng(seed)
    null = np.array(
        [
            normalized_mutual_info_score(rng.permutation(sys_arr[mask]), cond[mask])
            for _ in range(200)
        ]
    )
    per_cluster = {
        c: float(best.consensus[np.ix_(idx, idx)][np.triu_indices(len(idx), 1)].mean())
        for c in range(labels.max() + 1)
        if len(idx := np.where(labels == c)[0]) > 1
    }
    g = build_graph(x, min_co, min_npmi)
    edges = [(vocab[u], vocab[v], d["weight"]) for u, v, d in g.edges(data=True)]
    return SymptomClustering(
        vocab=vocab,
        labels=labels,
        resolution=best.resolution,
        stability=best.stability,
        modularity=best.modularity,
        sweep=[
            {
                "resolution": r.resolution,
                "n_clusters": r.n_clusters,
                "stability_ari": round(r.stability, 4),
                "modularity": round(r.modularity, 4),
            }
            for r in runs
        ],
        cluster_stability=per_cluster,
        cluster_names=name_clusters(x, vocab, labels, body_systems.reset_index(drop=True), cond),
        condition_cluster=cond,
        nmi_body_system=nmi,
        nmi_null_mean=float(null.mean()),
        nmi_p_value=float((1 + (null >= nmi).sum()) / (len(null) + 1)),
        edges=edges,
    )
