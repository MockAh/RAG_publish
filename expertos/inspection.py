"""Volcado legible de los clústeres de un k candidato, para la inspección humana de N4.

Vive aparte de `clustering.py` para que aquel siga siendo numérico puro: este
módulo es el único que cruza los labels con `excavador.db` (año, título).

"Más cercano al centroide" se mide por distancia euclídea al centroide de
k-means. Con vectores de norma 1 (N2), ||x − c||² = 1 − 2·x·c + ||c||², así
que el orden coincide con el de similitud coseno al centroide.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import numpy as np
from sklearn.cluster import KMeans

from excavador.models import PaperRecord


class PaperLookup(Protocol):
    def get_paper(self, paper_id: str) -> PaperRecord | None: ...


def dump_clusters(
    X: np.ndarray,
    paper_ids: list[str],
    k: int,
    excavador_storage: PaperLookup,
    out_path: Path,
    seed: int = 42,
    n_sample: int = 10,
) -> None:
    """Corre k-means con `k` y escribe un `.md` con, por clúster (de mayor a menor), su
    tamaño y sus `n_sample` papers más cercanos al centroide (todos si caben).

    Mismos parámetros de KMeans que `clustering.sweep_kmeans`, así que los labels
    coinciden con los del barrido para el mismo `k` y `seed`.
    """
    kmeans = KMeans(n_clusters=k, random_state=seed, n_init="auto").fit(X)
    labels = kmeans.labels_
    distances = np.linalg.norm(X - kmeans.cluster_centers_[labels], axis=1)

    cluster_ids = sorted(range(k), key=lambda c: (-int((labels == c).sum()), c))
    lines = [
        f"# Inspección de clústeres — k={k} (N4)",
        "",
        f"Papers: {len(paper_ids)} · seed={seed} · hasta {n_sample} papers por clúster, "
        "ordenados del más cercano al centroide al más lejano.",
        "",
    ]
    for cluster_id in cluster_ids:
        members = np.flatnonzero(labels == cluster_id)
        closest = members[np.argsort(distances[members], kind="stable")][:n_sample]
        lines += [f"## Clúster {cluster_id} — {len(members)} papers", ""]
        for index in closest:
            paper_id = paper_ids[index]
            paper = excavador_storage.get_paper(paper_id)
            if paper is None:
                raise ValueError(f"{paper_id} no está en excavador.db")
            year = paper.year if paper.year is not None else "s.f."
            lines.append(f"- {year} · {paper.title} · `{paper_id}`")
        lines.append("")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
