"""Vectores representativos de los papers indexados (N2).

Un vector por paper, entrada del clustering de N3. Corpus: solo los papers
con chunks en Chroma (158 indexados, herencia E3 de fase 03), no la tabla
`papers` completa de `excavador.db`; tras colapsar los alias de DOI_ALIASES
quedan 155 papers únicos (A6).

# ══════════════════════════════════════════════════════════════════════════
# REGLA CRÍTICA (congelada en docs/01-CONTRATOS-DE-DATOS_v11.md, convención
# de prefijos e5, OBLIGATORIA): un vector representativo es un DOCUMENTO, así
# que se embebe SIEMPRE con el prefijo "passage: " (vía
# `Embedder.embed_passages`), NUNCA con "query: ". Aplica a los dos caminos:
# "título. abstract" y la media de chunks.
# ══════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from biblioteca.config import Settings as BibliotecaSettings
from biblioteca.embedder import Embedder
from biblioteca.store import ChunkStore
from excavador.storage import Storage

logger = logging.getLogger(__name__)

# A6 (registro de fase 04): tres papers indexados dos veces con una variante del
# DOI que el dedup de fase 02 no capturó (compara DOI normalizado exacto; C5).
# Mismo título, año y autores. alias -> canónico; criterio en
# `canonicalize_paper_ids`. La duplicación persiste en excavador.db y Chroma (E3).
DOI_ALIASES: dict[str, str] = {
    # 1 chunk frente a 26
    "doi:10.15332/25005375/5376": "doi:10.15332/25005375.5376",
    # 1 chunk frente a 1: empate, gana el primero alfabéticamente
    "doi:10.22201/ppla.24487988e.2016.6.58438": "doi:10.22201/ppela.24487988e.2016.6.58438",
    # 1 chunk frente a 44
    "doi:10.37819/revhuman.v9i2.866": "doi:10.37819/humanrev.v9i2.866",
}


def get_indexed_paper_ids(
    biblioteca_settings: BibliotecaSettings,
    excavador_storage: Storage | None = None,
    chunk_store: ChunkStore | None = None,
) -> list[str]:
    """Devuelve (ordenados) los `paper_id` de `excavador.db` que tienen chunks en Chroma.

    `excavador_storage` y `chunk_store` son inyectables (tests); si faltan se
    abren desde `biblioteca_settings`.
    """
    storage = excavador_storage if excavador_storage is not None else Storage(biblioteca_settings.db_path)
    store = chunk_store if chunk_store is not None else ChunkStore(biblioteca_settings.chroma_dir)
    return sorted(paper.paper_id for paper in storage.all_papers() if store.has_paper(paper.paper_id))


def canonicalize_paper_ids(paper_ids: list[str]) -> list[str]:
    """Colapsa los alias de `DOI_ALIASES` a su `paper_id` canónico, sin repetidos.

    Criterio del canónico (fijado a mano en `DOI_ALIASES`, medido en Chroma al
    detectar A6): el DOI con más chunks indexados; si empatan, el primero
    alfabéticamente. Conserva el orden de primera aparición.
    """
    canonical: list[str] = []
    seen: set[str] = set()
    for paper_id in paper_ids:
        paper_id = DOI_ALIASES.get(paper_id, paper_id)
        if paper_id not in seen:
            seen.add(paper_id)
            canonical.append(paper_id)
    return canonical


def build_representative_vectors(
    paper_ids: list[str],
    excavador_storage: Storage,
    chunk_store: ChunkStore,
    embedder: Embedder,
) -> dict[str, np.ndarray]:
    """Genera un vector representativo por paper, con los alias ya colapsados.

    `paper_ids` pasa antes por `canonicalize_paper_ids` (A6): el resultado
    tiene una sola entrada por paper real, con clave canónica.

    Caso normal: `embed_passages(["<título>. <abstract>"])`. Si el paper no
    tiene abstract (indexado solo por PDF), media de los embeddings
    "passage: " de sus chunks, renormalizada a norma 1 para que viva en la
    misma escala que los vectores de e5 (el clustering de N3 compara por
    distancia).
    """
    paper_ids = canonicalize_paper_ids(paper_ids)
    papers = []
    for paper_id in paper_ids:
        paper = excavador_storage.get_paper(paper_id)
        if paper is None:
            raise ValueError(f"{paper_id} está indexado en Chroma pero no existe en excavador.db")
        papers.append(paper)

    with_abstract = [paper for paper in papers if paper.abstract.strip()]
    without_abstract = [paper for paper in papers if not paper.abstract.strip()]

    vectors: dict[str, np.ndarray] = {}

    # "passage: " lo antepone embed_passages (ver regla crítica arriba)
    texts = [f"{paper.title}. {paper.abstract}" for paper in with_abstract]
    embeddings = embedder.embed_passages(texts) if texts else []
    for paper, embedding in zip(with_abstract, embeddings, strict=True):
        vectors[paper.paper_id] = np.asarray(embedding, dtype=np.float32)

    for paper in without_abstract:
        vectors[paper.paper_id] = _mean_of_chunks(paper.paper_id, paper.title, chunk_store, embedder)

    logger.info(
        "build_representative_vectors: %d papers, %d con título+abstract, %d por media de chunks",
        len(vectors),
        len(with_abstract),
        len(without_abstract),
    )
    if without_abstract:
        logger.info("papers por media de chunks: %s", ", ".join(p.paper_id for p in without_abstract))
    return {paper_id: vectors[paper_id] for paper_id in paper_ids}


def _mean_of_chunks(paper_id: str, title: str, chunk_store: ChunkStore, embedder: Embedder) -> np.ndarray:
    """Media renormalizada de los embeddings "passage: " de todos los chunks de `paper_id`.

    `ChunkStore` no expone los embeddings guardados, así que se recuperan los
    textos con `retrieve` filtrado al paper (el título solo sirve de consulta
    para ordenar; con `top_k = count()` se traen todos) y se re-embeben con
    `embed_passages`: mismo modelo y mismo prefijo que en la indexación.
    """
    scored = chunk_store.retrieve(
        title, top_k=chunk_store.count(), filter_paper_ids=[paper_id], embedder=embedder
    )
    if not scored:
        raise ValueError(f"{paper_id} no tiene abstract ni chunks: no debería estar en el corpus indexado")
    embeddings = np.asarray(embedder.embed_passages([s.chunk.text for s in scored]), dtype=np.float32)
    mean = embeddings.mean(axis=0)
    return mean / np.linalg.norm(mean)


def save_vectors(vectors: dict[str, np.ndarray], out_path: Path) -> None:
    """Guarda `vectors` en `.npz` con cada `paper_id` como clave (N2: `.npy` suelto perdería el id)."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(out_path, **vectors)


def load_vectors(path: Path) -> dict[str, np.ndarray]:
    """Inverso exacto de `save_vectors`."""
    with np.load(Path(path), allow_pickle=False) as data:
        return {paper_id: data[paper_id] for paper_id in data.files}
