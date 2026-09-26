"""Barrido de clustering sobre los vectores representativos (N3).

k-means con k = 5–12 más HDBSCAN como contraste (decisión X2 del plan de
fase 04). El informe NO recomienda un k: esa elección es de N4, con
inspección humana de los clústeres.

Los vectores llegan de N2 ya en norma 1, así que no se reescalan: con norma
1, la distancia euclídea de k-means es monótona con la distancia coseno.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sklearn.cluster import HDBSCAN, KMeans
from sklearn.metrics import silhouette_score


@dataclass(frozen=True)
class KMeansResult:
    """Resultado de k-means para un k del barrido."""

    k: int
    labels: np.ndarray
    silhouette: float
    sizes: dict[int, int]


@dataclass(frozen=True)
class HDBSCANResult:
    """Resultado de la corrida de contraste de HDBSCAN; el label -1 es ruido."""

    labels: np.ndarray
    n_clusters: int
    n_noise: int


def _cluster_sizes(labels: np.ndarray) -> dict[int, int]:
    """Tamaño por clúster, con claves y valores `int` nativos (F5 de fase 02)."""
    values, counts = np.unique(labels, return_counts=True)
    return {int(v): int(c) for v, c in zip(values, counts)}


def load_matrix(vectors: dict[str, np.ndarray]) -> tuple[np.ndarray, list[str]]:
    """Convierte la salida de `load_vectors` en una matriz (n, dim) y su lista paralela
    de `paper_id`, ordenada por `paper_id` para que el orden sea determinista."""
    paper_ids = sorted(vectors)
    X = np.stack([vectors[paper_id] for paper_id in paper_ids])
    return X, paper_ids


def sweep_kmeans(X: np.ndarray, k_min: int = 5, k_max: int = 12, seed: int = 42) -> list[KMeansResult]:
    """Corre k-means para cada k en [k_min, k_max]; silhouette con métrica coseno."""
    results = []
    for k in range(k_min, k_max + 1):
        labels = KMeans(n_clusters=k, random_state=seed, n_init="auto").fit_predict(X)
        results.append(
            KMeansResult(
                k=k,
                labels=labels,
                silhouette=float(silhouette_score(X, labels, metric="cosine")),
                sizes=_cluster_sizes(labels),
            )
        )
    return results


def run_hdbscan(X: np.ndarray, min_cluster_size: int = 5) -> HDBSCANResult:
    """Una corrida de HDBSCAN con métrica coseno.

    `sklearn.cluster.HDBSCAN` acepta `metric="cosine"` directamente (cae al
    algoritmo brute, pues los árboles no soportan coseno), así que no hace
    falta la matriz precomputada `1 - X @ X.T`. HDBSCAN es determinista: no
    lleva semilla.
    """
    labels = HDBSCAN(min_cluster_size=min_cluster_size, metric="cosine", copy=True).fit_predict(X)
    return HDBSCANResult(
        labels=labels,
        n_clusters=len(set(labels.tolist()) - {-1}),
        n_noise=int((labels == -1).sum()),
    )


def _size_summary(sizes: list[int]) -> str:
    if not sizes:
        return "—"
    return f"{min(sizes)} / {max(sizes)} / {statistics.median(sizes):g}"


def report(
    sweep: list[KMeansResult], hdbscan: HDBSCANResult, paper_ids: list[str], out_path: Path
) -> None:
    """Escribe un informe Markdown del barrido. No recomienda un k (lo decide N4)."""
    lines = [
        "# Barrido de clustering (N3)",
        "",
        f"Papers: {len(paper_ids)}. Silhouette con métrica coseno. "
        "Este informe no recomienda un k: la elección es de N4 (inspección humana).",
        "",
        "## k-means",
        "",
        "| k | silhouette | tamaño min / max / mediana | tamaños |",
        "|---|---|---|---|",
    ]
    for result in sweep:
        sizes = sorted(result.sizes.values(), reverse=True)
        lines.append(
            f"| {result.k} | {result.silhouette:.4f} | {_size_summary(sizes)} | "
            f"{', '.join(map(str, sizes))} |"
        )

    cluster_sizes = sorted(
        (size for label, size in _cluster_sizes(hdbscan.labels).items() if label != -1), reverse=True
    )
    lines += [
        "",
        "## HDBSCAN (contraste)",
        "",
        f"- Clústeres: {hdbscan.n_clusters}",
        f"- Ruido (label -1): {hdbscan.n_noise} de {len(hdbscan.labels)}",
        f"- Tamaño min / max / mediana: {_size_summary(cluster_sizes)}",
        f"- Tamaños: {', '.join(map(str, cluster_sizes)) or '—'}",
        "",
    ]

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
