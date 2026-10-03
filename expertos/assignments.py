"""Persistencia de la asignación paper → experto (X5, N4).

Tabla SQLite `clusters(paper_id, expert_id, run_id)` en `excavador.db`, junto
a `llm_calls`. `expert_id` = `C{label}` de k-means (C3: `expert_id` =
cluster_id), la misma nomenclatura que A8/A9 del registro. `run_id` nombra la
corrida (`kmeans-k9-seed42-<hash8>`) y la ata a los vectores de entrada: si se
regeneran con otro contenido, cambia el hash y la partición vieja no se
confunde con la nueva. Volver a guardar el mismo `run_id` la reemplaza entera,
así que la operación es idempotente.

Una corrida derivada (`<run_id>+merge-C8-C0`) reasigna un clúster entero a
otro sin tocar la partición de origen, para poder revertir la fusión.

`EXCLUDED_PAPER_IDS` es la stoplist del corpus de fase 04. Se aplica al LEER
(`load_corpus_assignment`), no al construir los vectores: excluir en
`vectors.py` cambiaría el hash de `expert_vectors.npz`, obligaría a
re-clusterizar e invalidaría la inspección de N4 (A8). La tabla `clusters`
sigue guardando la partición tal como salió de k-means.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import NamedTuple

import numpy as np

# E4 (registro de fase 04): metadatos corruptos en origen. Titula «Modos y usos del
# pensamiento de Bolívar Echeverría», pero DOI y abstract son de otro artículo
# (American Journal of Physical Anthropology, metilación de ADN en dientes). Su
# vector se construyó con ese abstract ajeno, así que no representa nada real.
EXCLUDED_PAPER_IDS: frozenset[str] = frozenset({"doi:10.1002/ajpa.22921"})


class PrimaryWork(NamedTuple):
    """Quién escribió de verdad el texto indexado de un paper, cuando `authors` no lo dice."""

    real_author: str
    attribution_note: str


# A17 (registro de fase 04): papers cuyo texto indexado no es de quien figura en `authors`.
# No se excluyen —citarlos puede ser correcto—, pero `real_author` sustituye a `authors` en el
# prompt de síntesis (N8) y toda claim que los cite queda marcada para revisión manual (N10).
# Lista cerrada, salida de un censo heurístico leyendo chunks: si N10 encuentra otro, se añade aquí.
PRIMARY_WORKS: dict[str, PrimaryWork] = {
    "doi:10.29166/economia.v70i111.1393": PrimaryWork(
        real_author="Karl Marx",
        attribution_note=(
            "Texto de Marx: El capital, Libro I, capítulo I («La mercancía»), en la traducción de "
            "Bolívar Echeverría (1976), republicada en 2018. Es palabra de Marx, no de Echeverría "
            "ni de un comentarista."
        ),
    ),
    "doi:10.22201/cisan.24487228e.2009.01.37": PrimaryWork(
        real_author="Bolívar Echeverría (entrevistado)",
        attribution_note=(
            "Entrevista de 2009: las respuestas son palabras de Echeverría; las preguntas, de los "
            "entrevistadores (Díaz de la Serna, Valdés Ugalde, Sigüenza Reyes), que son quienes figuran "
            "como autores en los metadatos."
        ),
    ),
    "doi:10.17141/iconos.17.2003.502": PrimaryWork(
        real_author="Bolívar Echeverría (entrevistado)",
        attribution_note=(
            "Diálogo de 2003: las respuestas son palabras de Echeverría; las preguntas y la presentación, "
            "de los entrevistadores (Figueroa, Cerbino), que son quienes figuran como autores en los metadatos."
        ),
    ),
    "openalex:W1675963835": PrimaryWork(
        real_author="Laura Romero (nota de prensa)",
        attribution_note=(
            "Nota de prensa de la UNAM sobre el premio a Vuelta de siglo (2007). Parafrasea a Echeverría: "
            "no son sus palabras, aunque los metadatos lo incluyan como autor."
        ),
    ),
}

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


def load_corpus_assignment(db_path: Path, run_id: str) -> dict[str, str]:
    """`load_assignment` sin los papers de `EXCLUDED_PAPER_IDS`: la vista del corpus que
    usa la fase 04 (etiquetado, síntesis)."""
    return {
        paper_id: expert_id
        for paper_id, expert_id in load_assignment(db_path, run_id).items()
        if paper_id not in EXCLUDED_PAPER_IDS
    }


def merge_run_id(run_id: str, source: str, target: str) -> str:
    """`<run_id>+merge-<source>-<target>`."""
    return f"{run_id}+merge-{source}-{target}"


def merge_clusters(db_path: Path, run_id: str, source: str, target: str) -> str:
    """Guarda como corrida derivada la partición de `run_id` con todo `source` reasignado a
    `target`; la corrida de origen no se toca. Devuelve el `run_id` derivado."""
    assignment = load_assignment(db_path, run_id)
    expert_ids = set(assignment.values())
    if source == target or not {source, target} <= expert_ids:
        raise ValueError(f"fusión inválida {source} → {target} en clusters[run_id={run_id}]")
    derived = merge_run_id(run_id, source, target)
    merged = {paper_id: target if expert_id == source else expert_id for paper_id, expert_id in assignment.items()}
    save_assignment(db_path, derived, merged)
    return derived
