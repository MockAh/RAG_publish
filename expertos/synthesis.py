"""Modo síntesis 1/2: sub-consultas y retrieval por partición (N7; X3, X4, X7).

Dos fases separadas, y esta es solo la primera:

1. El LLM propone 8–12 sub-consultas que cubren el tema del clúster desde ángulos
   distintos (`generate_subqueries`, UNA llamada por clúster).
2. El código recupera, para cada sub-consulta, los chunks de la partición del clúster
   (`retrieve_for_expert`) y los une por `chunk_id` (`collect_candidate_chunks`).

La redacción de claims y la clasificación de `stance` son N8, que parte del archivo
`{synthesis_dir}/_retrieval/{expert_id}.json`: un fallo en N8 no repite ni el retrieval
ni la llamada al LLM.

Límites heredados de fase 03 que fijan el diseño:

- L2: el retrieval empareja por tema, no por postura. Las sub-consultas nunca piden
  «críticas a X»: se recupera por tema y N8 clasifica la postura leyendo cada pasaje.
- L1: el score no mide confianza (banda útil 0.83–0.90, el ruido vive dentro). Ningún
  chunk se descarta por score: N8 recibe todos los candidatos y el LLM juzga leyendo.
- L3: ninguna sub-consulta tiene un pasaje que la responda entera; por eso son frases
  de contenido para búsqueda semántica, no preguntas de síntesis.

Los chunks `from_abstract` se conservan (son citables); la preferencia por el chunk de
PDF cuando ambos sustentan una claim (X7) la aplica el prompt de N8, no un filtro aquí.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar, Protocol

import numpy as np
from pydantic import BaseModel, field_validator

from biblioteca.models import ScoredChunk
from excavador.models import PaperRecord
from expertos.assignments import load_corpus_assignment
from expertos.inspection import PaperLookup
from expertos.labeling import ClusterLabel, _clean, select_representatives
from expertos.llm import LLMClient
from expertos.persistence import _atomic_write_text, _synthesis_path

logger = logging.getLogger(__name__)

N_MIN_QUERIES = 8
N_MAX_QUERIES = 12
RETRIEVAL_SUBDIR = "_retrieval"


class SubQueries(BaseModel):
    """Salida del LLM: sub-consultas para búsqueda semántica sobre la partición.

    Los límites viven en variables de clase para que `subqueries_schema(n_min, n_max)`
    derive una subclase con otros sin cambiar el campo (el cliente valida con
    `schema.model_validate_json`, que no admite parámetros).
    """

    n_min: ClassVar[int] = N_MIN_QUERIES
    n_max: ClassVar[int] = N_MAX_QUERIES

    queries: list[str]

    @field_validator("queries")
    @classmethod
    def _count_and_uniqueness(cls, queries: list[str]) -> list[str]:
        """Entre `n_min` y `n_max` consultas no vacías y sin duplicados exactos (tras quitar espacios)."""
        queries = [query.strip() for query in queries]
        if any(not query for query in queries):
            raise ValueError("hay sub-consultas vacías")
        if not cls.n_min <= len(queries) <= cls.n_max:
            raise ValueError(f"se esperaban entre {cls.n_min} y {cls.n_max} sub-consultas, llegaron {len(queries)}")
        duplicated = sorted({query for query in queries if queries.count(query) > 1})
        if duplicated:
            raise ValueError(f"sub-consultas duplicadas: {duplicated}")
        return queries


def subqueries_schema(n_min: int, n_max: int) -> type[SubQueries]:
    """`SubQueries` con los límites `[n_min, n_max]`."""
    if not 1 <= n_min <= n_max:
        raise ValueError(f"límites inválidos: n_min={n_min}, n_max={n_max}")
    if (n_min, n_max) == (SubQueries.n_min, SubQueries.n_max):
        return SubQueries
    return type("SubQueries", (SubQueries,), {"n_min": n_min, "n_max": n_max})


def build_subqueries_prompt(
    label: ClusterLabel, papers: Sequence[PaperRecord], n_min: int, n_max: int
) -> tuple[str, str]:
    """(system, user) para pedir las sub-consultas de un clúster."""
    system = f"""Eres un investigador que prepara la búsqueda bibliográfica para sintetizar un
grupo temático de papers sobre la obra de Bolívar Echeverría.

Vas a escribir entre {n_min} y {n_max} sub-consultas. Se usarán para búsqueda semántica
(similitud de embeddings) en un corpus de pasajes de esos papers; los pasajes recuperados
servirán después para redactar una síntesis citada del grupo.

Reglas:
- Cada sub-consulta es una frase de contenido que se parece a lo que diría un pasaje
  relevante: conceptos, autores, tesis, contextos o casos concretos. No escribas
  preguntas retóricas ni preguntas de síntesis («¿cómo se relaciona A con B?»): ningún
  pasaje suelto las responde.
- Cubre ángulos complementarios del tema: conceptos centrales, sus fuentes y diálogos
  teóricos, aplicaciones o casos, contextos históricos, debates y desarrollos posteriores.
  No reformules la misma idea con otras palabras.
- No pidas críticas, objeciones ni contradicciones («críticas a X», «limitaciones de X»):
  la búsqueda empareja por tema, no por postura, y devolvería exposiciones de X. Busca
  por tema; la postura de cada pasaje se juzgará después, leyéndolo.
- No uses «Bolívar Echeverría» como sub-consulta por sí solo: todo el corpus trata de él.
- Escribe en español, que es la lengua dominante del corpus; conserva en su idioma
  original los términos técnicos que lo exijan.
- Responde con un objeto JSON con la clave "queries" (lista de cadenas)."""

    lines = [
        f"Tema del grupo: {label.topic_label}",
        f"Descripción: {label.one_liner}",
        f"Palabras clave: {', '.join(label.keywords)}",
        "",
        f"Títulos de papers representativos ({len(papers)}, del más central al menos central):",
    ]
    lines += [f"{i}. {_clean(paper.title)}" for i, paper in enumerate(papers, start=1)]
    return system, "\n".join(lines)


def generate_subqueries(
    expert_id: str,
    label: ClusterLabel,
    papers: Sequence[PaperRecord],
    llm_client: LLMClient,
    n_min: int = N_MIN_QUERIES,
    n_max: int = N_MAX_QUERIES,
    *,
    run_id: str | None = None,
) -> list[str]:
    """Una llamada al LLM: sub-consultas de `expert_id` para recuperar su partición por tema.

    Una respuesta fuera de `[n_min, n_max]` o con duplicados la rechaza el schema
    (`LLMOutputError`, que el cliente no reintenta). `run_id` solo va al `context` de `llm_calls`.
    """
    system, user = build_subqueries_prompt(label, papers, n_min, n_max)
    context = {"task": "synthesis.subqueries", "expert_id": expert_id}
    if run_id is not None:
        context["run_id"] = run_id
    return llm_client.complete_json(system, user, subqueries_schema(n_min, n_max), context=context).queries


class Retriever(Protocol):
    """Lo que `retrieve_for_expert` usa de `biblioteca.store.ChunkStore`."""

    def retrieve(self, query: str, top_k: int = 8, filter_paper_ids: list[str] | None = None) -> list[ScoredChunk]:
        ...


def partition_paper_ids(expert_id: str, run_id: str, db_path: Path) -> list[str]:
    """Papers de `expert_id` en `clusters[run_id]`, sin la stoplist E4, ordenados."""
    paper_ids = sorted(
        paper_id for paper_id, eid in load_corpus_assignment(db_path, run_id).items() if eid == expert_id
    )
    if not paper_ids:
        # Vacío no es «sin filtro»: `ChunkStore.retrieve` buscaría en todo el corpus.
        raise ValueError(f"{expert_id} no tiene papers en clusters[run_id={run_id}]")
    return paper_ids


def retrieve_for_expert(
    expert_id: str,
    run_id: str,
    queries: Sequence[str],
    chunk_store: Retriever,
    top_k: int = 8,
    *,
    db_path: Path,
) -> dict[str, list[ScoredChunk]]:
    """Sub-consulta → chunks recuperados (orden del store), restringidos a la partición de `expert_id`. Sin LLM."""
    paper_ids = partition_paper_ids(expert_id, run_id, db_path)
    retrieved = {}
    for query in queries:
        retrieved[query] = chunk_store.retrieve(query, top_k=top_k, filter_paper_ids=list(paper_ids))
        stray = {sc.chunk.paper_id for sc in retrieved[query]} - set(paper_ids)
        if stray:
            raise RuntimeError(f"el store devolvió chunks fuera de la partición de {expert_id}: {sorted(stray)}")
    return retrieved


class CandidateChunk(ScoredChunk):
    """Un chunk candidato para N8: el mejor score con que salió y las sub-consultas que lo trajeron."""

    queries: list[str]


def collect_candidate_chunks(retrieved: dict[str, list[ScoredChunk]]) -> list[CandidateChunk]:
    """Une por `chunk_id`: cada chunk aparece una vez, con su mejor score y las consultas
    (en el orden de `retrieved`) que lo recuperaron. Sin filtrar por score (L1).
    Orden: score descendente, `chunk_id` como desempate."""
    candidates: dict[str, CandidateChunk] = {}
    for query, scored_chunks in retrieved.items():
        for sc in scored_chunks:
            chunk_id = sc.chunk.chunk_id
            existing = candidates.get(chunk_id)
            if existing is None:
                candidates[chunk_id] = CandidateChunk(
                    chunk=sc.chunk, score=float(sc.score), from_abstract=bool(sc.from_abstract), queries=[query]
                )
                continue
            if query not in existing.queries:
                existing.queries.append(query)
            existing.score = max(existing.score, float(sc.score))
    return sorted(candidates.values(), key=lambda c: (-c.score, c.chunk.chunk_id))


class RetrievalRecord(BaseModel):
    """Material intermedio de un Experto entre N7 y N8 (`_retrieval/{expert_id}.json`).

    Modelo interno de fase 04, no es contrato. Basta para que N8 redacte sin volver a
    llamar al LLM ni a Chroma: guarda el texto de cada chunk, no solo su id.
    """

    expert_id: str
    run_id: str
    created_at: datetime
    llm_provider: str
    llm_model: str
    topic_label: str
    paper_ids: list[str]  # partición consultada (sin stoplist)
    top_k: int
    queries: list[str]
    candidates: list[CandidateChunk]


def retrieval_path(expert_id: str, *, synthesis_dir: Path) -> Path:
    """`{synthesis_dir}/_retrieval/{expert_id}.json`."""
    return _synthesis_path(Path(synthesis_dir) / RETRIEVAL_SUBDIR, expert_id)


def save_retrieval(record: RetrievalRecord, *, synthesis_dir: Path) -> Path:
    """Guarda `record` de forma atómica (reemplaza el anterior) y devuelve la ruta."""
    path = retrieval_path(record.expert_id, synthesis_dir=synthesis_dir)
    _atomic_write_text(path, record.model_dump_json(indent=2) + "\n")
    return path


def load_retrieval(expert_id: str, *, synthesis_dir: Path) -> RetrievalRecord | None:
    """El material de retrieval de `expert_id`, o `None` si aún no existe."""
    path = retrieval_path(expert_id, synthesis_dir=synthesis_dir)
    if not path.exists():
        return None
    return RetrievalRecord.model_validate_json(path.read_text(encoding="utf-8"))


def run_expert_retrieval(
    expert_id: str,
    llm_client: LLMClient,
    chunk_store: Retriever,
    *,
    run_id: str,
    label: ClusterLabel,
    vectors: dict[str, np.ndarray],
    db_path: Path,
    excavador_storage: PaperLookup,
    synthesis_dir: Path,
    n_papers: int = 10,
    top_k: int = 8,
) -> RetrievalRecord:
    """N7 completo para un Experto: sub-consultas (1 llamada) → retrieval → candidatos → archivo.

    Los papers del prompt son los `n_papers` más cercanos al centroide (los mismos que vio
    el etiquetado de N5). Si el LLM falla no se escribe nada; el archivo solo aparece entero.
    """
    papers = select_representatives(
        expert_id, run_id, n_papers, vectors=vectors, db_path=db_path, excavador_storage=excavador_storage
    )
    queries = generate_subqueries(expert_id, label, papers, llm_client, run_id=run_id)
    retrieved = retrieve_for_expert(expert_id, run_id, queries, chunk_store, top_k, db_path=db_path)
    record = RetrievalRecord(
        expert_id=expert_id,
        run_id=run_id,
        created_at=datetime.now(timezone.utc),
        llm_provider=str(getattr(llm_client, "provider", "unknown")),
        llm_model=str(getattr(llm_client, "model", "unknown")),
        topic_label=label.topic_label,
        paper_ids=partition_paper_ids(expert_id, run_id, db_path),
        top_k=top_k,
        queries=queries,
        candidates=collect_candidate_chunks(retrieved),
    )
    save_retrieval(record, synthesis_dir=synthesis_dir)
    return record
