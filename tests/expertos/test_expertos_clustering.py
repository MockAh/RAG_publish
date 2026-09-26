"""Tests para expertos.clustering (N3)."""

from pathlib import Path

import numpy as np
import pytest
from sklearn.datasets import make_blobs

from expertos.clustering import load_matrix, report, run_hdbscan, sweep_kmeans

N_POINTS = 20


def _blobs(n_samples: list[int] | int = N_POINTS, seed: int = 0) -> np.ndarray:
    """Tres blobs bien separados en dirección (centros ortogonales), normalizados a norma 1."""
    centers = 10 * np.eye(3, 8)
    X, _ = make_blobs(n_samples=n_samples, centers=centers, cluster_std=0.5, random_state=seed)
    return X / np.linalg.norm(X, axis=1, keepdims=True)


def test_load_matrix_sorts_by_paper_id() -> None:
    vectors = {"doi:b": np.array([0.0, 1.0]), "doi:a": np.array([1.0, 0.0])}

    X, paper_ids = load_matrix(vectors)

    assert paper_ids == ["doi:a", "doi:b"]
    assert X.shape == (2, 2)
    np.testing.assert_array_equal(X[0], vectors["doi:a"])


def test_sweep_returns_one_result_per_k_and_sizes_sum_to_total() -> None:
    X = _blobs()

    sweep = sweep_kmeans(X, k_min=2, k_max=6)

    assert [r.k for r in sweep] == [2, 3, 4, 5, 6]
    for result in sweep:
        assert len(result.sizes) == result.k
        assert sum(result.sizes.values()) == N_POINTS


def test_silhouette_discriminates_correct_k_on_easy_case() -> None:
    X = _blobs()

    by_k = {r.k: r.silhouette for r in sweep_kmeans(X, k_min=2, k_max=8)}

    assert by_k[3] > by_k[2]
    assert by_k[3] > by_k[8]


def test_hdbscan_reports_noise_when_min_cluster_size_exceeds_a_blob() -> None:
    X = _blobs(n_samples=[3, 9, 8])

    result = run_hdbscan(X, min_cluster_size=5)

    assert result.n_noise > 0
    assert len(result.labels) == 20


def test_same_seed_gives_same_labels() -> None:
    X = _blobs()

    first = sweep_kmeans(X, k_min=3, k_max=5, seed=7)
    second = sweep_kmeans(X, k_min=3, k_max=5, seed=7)

    for a, b in zip(first, second):
        np.testing.assert_array_equal(a.labels, b.labels)


def test_report_lists_k_and_silhouette_of_each_row(tmp_path: Path) -> None:
    X = _blobs()
    sweep = sweep_kmeans(X, k_min=2, k_max=4)
    out_path = tmp_path / "sub" / "report.md"

    report(sweep, run_hdbscan(X), [f"doi:{i}" for i in range(N_POINTS)], out_path)

    text = out_path.read_text(encoding="utf-8")
    for result in sweep:
        assert f"| {result.k} | {result.silhouette:.4f} |" in text


@pytest.mark.slow
def test_real_sweep_on_155_vectors(tmp_path: Path) -> None:
    """Con los vectores reales de N2 (desde la raíz del repo): 155 papers, sweep completo e informe."""
    from expertos.config import Settings
    from expertos.vectors import load_vectors

    X, paper_ids = load_matrix(load_vectors(Settings().expert_vectors_path))
    assert X.shape == (155, 1024)

    sweep = sweep_kmeans(X)
    out_path = tmp_path / "cluster_sweep_report.md"
    report(sweep, run_hdbscan(X), paper_ids, out_path)

    assert [r.k for r in sweep] == list(range(5, 13))
    assert all(sum(r.sizes.values()) == 155 for r in sweep)
    assert out_path.read_text(encoding="utf-8").strip()
