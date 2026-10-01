"""Tests para expertos.assignments (N4)."""

import re
from pathlib import Path

import numpy as np

import pytest

from expertos.assignments import (
    EXCLUDED_PAPER_IDS,
    labels_to_assignment,
    load_assignment,
    load_corpus_assignment,
    make_run_id,
    merge_clusters,
    save_assignment,
)
from expertos.vectors import save_vectors


def test_labels_to_assignment_uses_native_str_expert_ids() -> None:
    assignment = labels_to_assignment(["doi:a", "doi:b"], np.array([2, 0], dtype=np.int32))

    assert assignment == {"doi:a": "C2", "doi:b": "C0"}
    assert all(type(v) is str for v in assignment.values())


def test_save_load_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "excavador.db"
    assignment = {"doi:a": "C1", "doi:b": "C0"}

    save_assignment(db_path, "kmeans-k9-seed42-0123abcd", assignment)

    assert load_assignment(db_path, "kmeans-k9-seed42-0123abcd") == assignment
    assert load_assignment(db_path, "otra-corrida") == {}


def test_saving_same_run_replaces_it_and_leaves_other_runs(tmp_path: Path) -> None:
    db_path = tmp_path / "excavador.db"
    save_assignment(db_path, "run-a", {"doi:a": "C1", "doi:b": "C0"})
    save_assignment(db_path, "run-b", {"doi:a": "C5"})

    save_assignment(db_path, "run-a", {"doi:a": "C3"})

    assert load_assignment(db_path, "run-a") == {"doi:a": "C3"}
    assert load_assignment(db_path, "run-b") == {"doi:a": "C5"}


def test_run_id_is_tied_to_vectors_content(tmp_path: Path) -> None:
    path_a, path_b, path_a_again = tmp_path / "a.npz", tmp_path / "b.npz", tmp_path / "a2.npz"
    save_vectors({"doi:a": np.array([1.0, 0.0], dtype=np.float32)}, path_a)
    save_vectors({"doi:a": np.array([0.0, 1.0], dtype=np.float32)}, path_b)
    save_vectors({"doi:a": np.array([1.0, 0.0], dtype=np.float32)}, path_a_again)

    run_a = make_run_id(9, 42, path_a)

    assert re.fullmatch(r"kmeans-k9-seed42-[0-9a-f]{8}", run_a)
    assert make_run_id(9, 42, path_b) != run_a
    assert make_run_id(9, 42, path_a_again) == run_a  # mismo contenido, mismo run_id


def test_merge_creates_derived_run_and_leaves_original_intact(tmp_path: Path) -> None:
    db_path = tmp_path / "excavador.db"
    original = {"doi:a": "C0", "doi:b": "C8", "doi:c": "C8", "doi:d": "C1"}
    save_assignment(db_path, "kmeans-k9-seed42-0123abcd", original)

    derived = merge_clusters(db_path, "kmeans-k9-seed42-0123abcd", "C8", "C0")

    assert derived == "kmeans-k9-seed42-0123abcd+merge-C8-C0"
    assert load_assignment(db_path, derived) == {"doi:a": "C0", "doi:b": "C0", "doi:c": "C0", "doi:d": "C1"}
    assert load_assignment(db_path, "kmeans-k9-seed42-0123abcd") == original


@pytest.mark.parametrize("source, target", [("C8", "C8"), ("C9", "C0"), ("C8", "C5")])
def test_merge_rejects_unknown_or_identical_clusters(tmp_path: Path, source: str, target: str) -> None:
    db_path = tmp_path / "excavador.db"
    save_assignment(db_path, "run", {"doi:a": "C0", "doi:b": "C8"})

    with pytest.raises(ValueError, match="fusión inválida"):
        merge_clusters(db_path, "run", source, target)


def test_corpus_assignment_drops_stoplisted_papers_but_table_keeps_them(tmp_path: Path) -> None:
    db_path = tmp_path / "excavador.db"
    [excluded] = EXCLUDED_PAPER_IDS
    save_assignment(db_path, "run", {"doi:a": "C8", excluded: "C8"})

    assert load_corpus_assignment(db_path, "run") == {"doi:a": "C8"}
    assert excluded in load_assignment(db_path, "run")
