"""Tests para expertos.assignments (N4)."""

from pathlib import Path

import numpy as np

from expertos.assignments import labels_to_assignment, load_assignment, make_run_id, save_assignment


def test_labels_to_assignment_uses_native_str_expert_ids() -> None:
    assignment = labels_to_assignment(["doi:a", "doi:b"], np.array([2, 0], dtype=np.int32))

    assert assignment == {"doi:a": "C2", "doi:b": "C0"}
    assert all(type(v) is str for v in assignment.values())


def test_save_load_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "excavador.db"
    assignment = {"doi:a": "C1", "doi:b": "C0"}

    save_assignment(db_path, make_run_id(9, 42), assignment)

    assert make_run_id(9, 42) == "kmeans-k9-seed42"
    assert load_assignment(db_path, "kmeans-k9-seed42") == assignment
    assert load_assignment(db_path, "otra-corrida") == {}


def test_saving_same_run_replaces_it_and_leaves_other_runs(tmp_path: Path) -> None:
    db_path = tmp_path / "excavador.db"
    save_assignment(db_path, "run-a", {"doi:a": "C1", "doi:b": "C0"})
    save_assignment(db_path, "run-b", {"doi:a": "C5"})

    save_assignment(db_path, "run-a", {"doi:a": "C3"})

    assert load_assignment(db_path, "run-a") == {"doi:a": "C3"}
    assert load_assignment(db_path, "run-b") == {"doi:a": "C5"}
