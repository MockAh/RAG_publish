"""Tests para expertos.inspection (N4)."""

import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.cluster import KMeans
from sklearn.datasets import make_blobs

from excavador.models import PaperRecord
from expertos.inspection import dump_clusters


def _paper(paper_id: str) -> PaperRecord:
    return PaperRecord(
        paper_id=paper_id,
        doi=None,
        title=f"Título {paper_id}",
        authors=["Autora"],
        year=2020,
        venue=None,
        abstract="Un abstract.",
        source_api="openalex",
        work_type="article",
        pdf_path=None,
        relevance_score=0.9,
        references_ids=[],
        ingested_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


class InspectionDummyStorage:
    def __init__(self, paper_ids: list[str]) -> None:
        self._papers = {paper_id: _paper(paper_id) for paper_id in paper_ids}

    def get_paper(self, paper_id: str) -> PaperRecord | None:
        return self._papers.get(paper_id)


def _blocks(text: str) -> list[tuple[int, int, list[str]]]:
    """(cluster_id, tamaño, paper_ids listados en orden) por cada bloque del dump."""
    blocks = []
    for header, body in re.findall(r"## Clúster (\d+ — \d+) papers\n(.*?)(?=\n## |\Z)", text, re.S):
        cluster_id, size = (int(x) for x in header.split(" — "))
        blocks.append((cluster_id, size, re.findall(r"`([^`]+)`", body)))
    return blocks


def _unequal_blobs() -> tuple[np.ndarray, list[str]]:
    centers = 10 * np.eye(3, 8)
    X, _ = make_blobs(n_samples=[12, 7, 4], centers=centers, cluster_std=0.5, random_state=0)
    X = X / np.linalg.norm(X, axis=1, keepdims=True)
    return X, [f"doi:{i:02d}" for i in range(len(X))]


def test_one_block_per_cluster_sorted_by_size_and_members_belong(tmp_path: Path) -> None:
    X, paper_ids = _unequal_blobs()
    out_path = tmp_path / "sub" / "inspect.md"

    dump_clusters(X, paper_ids, 3, InspectionDummyStorage(paper_ids), out_path, seed=42, n_sample=5)

    blocks = _blocks(out_path.read_text(encoding="utf-8"))
    labels = KMeans(n_clusters=3, random_state=42, n_init="auto").fit_predict(X)
    assert len(blocks) == 3
    assert [size for _, size, _ in blocks] == [12, 7, 4]
    for cluster_id, size, listed in blocks:
        assert len(listed) == min(size, 5)  # clúster de 4 ≤ n_sample: se lista entero
        assert all(labels[paper_ids.index(paper_id)] == cluster_id for paper_id in listed)


def test_closest_to_centroid_listed_first(tmp_path: Path) -> None:
    # Un solo clúster en el círculo unidad, simétrico respecto a 0°: el centroide cae sobre
    # el eje de 0°, así que el orden por cercanía es 0°, luego ±10°, ±40°, ±80°.
    angles = [80, -40, 10, 0, -80, 40, -10]
    X = np.array([[np.cos(np.radians(a)), np.sin(np.radians(a))] for a in angles])
    paper_ids = [f"deg:{a}" for a in angles]
    out_path = tmp_path / "inspect.md"

    dump_clusters(X, paper_ids, 1, InspectionDummyStorage(paper_ids), out_path, n_sample=5)

    [(_, size, listed)] = _blocks(out_path.read_text(encoding="utf-8"))
    assert size == 7
    assert listed[0] == "deg:0"
    assert set(listed[1:3]) == {"deg:10", "deg:-10"}
    assert set(listed[3:5]) == {"deg:40", "deg:-40"}
