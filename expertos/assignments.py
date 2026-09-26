"""Persistencia de la asignación paper → experto (X5, N4).

Tabla SQLite `clusters(paper_id, expert_id, run_id)` en `excavador.db`, junto
a `llm_calls`. `expert_id` = `C{label}` de k-means (C3: `expert_id` =
cluster_id), la misma nomenclatura que A8/A9 del registro. `run_id` nombra la
corrida (`kmeans-k9-seed42-<hash8>`) y la ata a los vectores de entrada: si se
regeneran con otro contenido, cambia el hash y la partición vieja no se
confunde con la nueva. Volver a guardar el mismo `run_id` la reemplaza entera,
así que la operación es idempotente.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import numpy as np

_CREATE_CLUSTERS = """
CREATE TABLE IF NOT EXISTS clusters (
    paper_id TEXT NOT NULL,
    expert_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    PRIMARY KEY (run_id, paper_id)
)
"""


def make_run_id(k: int, seed: int, vectors_path: Path) -> str:
    """`kmeans-k{k}-seed{seed}-<hash8>`, con los 8 primeros caracteres hex del SHA-256 de
    `vectors_path` (`np.savez` es determinista: mismo contenido, mismo hash)."""
    digest = hashlib.sha256(Path(vectors_path).read_bytes()).hexdigest()
    return f"kmeans-k{k}-seed{seed}-{digest[:8]}"


def labels_to_assignment(paper_ids: list[str], labels: np.ndarray) -> dict[str, str]:
    """`paper_id` → `expert_id` (`C{label}`), con tipos nativos (F5 de fase 02)."""
    return {paper_id: f"C{int(label)}" for paper_id, label in zip(paper_ids, labels, strict=True)}


def save_assignment(db_path: Path, run_id: str, assignment: dict[str, str]) -> None:
    """Reemplaza, en una sola transacción, todas las filas de `run_id` por `assignment`."""
    with sqlite3.connect(db_path) as conn:
        conn.execute(_CREATE_CLUSTERS)
        conn.execute("DELETE FROM clusters WHERE run_id = ?", (run_id,))
        conn.executemany(
            "INSERT INTO clusters (paper_id, expert_id, run_id) VALUES (?, ?, ?)",
            [(paper_id, expert_id, run_id) for paper_id, expert_id in sorted(assignment.items())],
        )
    conn.close()


def load_assignment(db_path: Path, run_id: str) -> dict[str, str]:
    """Inverso de `save_assignment`; vacío si `run_id` no existe."""
    with sqlite3.connect(db_path) as conn:
        conn.execute(_CREATE_CLUSTERS)
        rows = conn.execute("SELECT paper_id, expert_id FROM clusters WHERE run_id = ?", (run_id,)).fetchall()
    conn.close()
    return dict(rows)
