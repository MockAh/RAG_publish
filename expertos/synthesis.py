"""Modo síntesis: sub-consultas y retrieval por partición (N7), claims validadas (N8). X3, X4, X7.

Dos fases separadas. La primera (N7):

1. El LLM propone 8–12 sub-consultas que cubren el tema del clúster desde ángulos
   distintos (`generate_subqueries`, UNA llamada por clúster).
2. El código recupera, para cada sub-consulta, los chunks de la partición del clúster
   (`retrieve_for_expert`) y los une por `chunk_id` (`collect_candidate_chunks`).

La segunda (N8, al final del módulo) redacta `summary` y `key_claims` desde el archivo
`{synthesis_dir}/_retrieval/{expert_id}.json`: un fallo en N8 no repite ni el retrieval
ni la llamada al LLM de N7.

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
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar, NamedTuple, Protocol

import numpy as np
from pydantic import BaseModel, ValidationError, field_validator

from biblioteca.models import ScoredChunk
from excavador.models import PaperRecord
from expertos.assignments import PRIMARY_WORKS, PrimaryWork, load_corpus_assignment
from expertos.inspection import PaperLookup
from expertos.labeling import ClusterLabel, _clean, select_representatives
from expertos.llm import LLMClient
from expertos.models import Claim, Synthesis, check_summary
from expertos.persistence import _atomic_write_text, _synthesis_path, save_synthesis

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


# --- N8 · modo síntesis 2/2: claims validadas -----------------------------------------
#
# Una llamada por Experto sobre los candidatos de N7. El LLM redacta `summary` y
# `key_claims`; el código decide qué sobrevive. Una claim que cita un `chunk_id` fuera de
# los recuperados se descarta entera, sin repararla (X3), y queda registrada con su motivo
# en `{synthesis_dir}/_draft/{expert_id}.json`. Una claim que cita obra primaria
# (`PRIMARY_WORKS`, A17) se conserva, porque puede ser legítima, pero se marca ahí mismo para
# que N10 la revise a mano.
#
# El prompt no muestra el score de los candidatos (L1: no mide confianza) y advierte de que
# el orden no indica relevancia.

DRAFT_SUBDIR = "_draft"
N_MIN_CLAIMS = 6
N_MAX_CLAIMS = 15


class ClaimDraft(BaseModel):
    """Claim tal como la propone el LLM, antes de validarla contra C3.

    `stance` es `str` y `supporting_chunks` admite la lista vacía: así una claim inválida
    se descarta sola, sin invalidar la respuesta entera (y la llamada) por una claim.
    """

    text: str
    supporting_chunks: list[str]
    stance: str


class DraftOutput(BaseModel):
    """Salida del LLM en N8. Un `summary` fuera de 300–800 palabras invalida la respuesta (C3)."""

    summary: str
    key_claims: list[ClaimDraft]

    _summary_fits_c3 = field_validator("summary")(check_summary)


class DiscardedClaim(BaseModel):
    claim: ClaimDraft
    reason: str


class PrimaryWorkFlag(BaseModel):
    """Claim conservada que cita obra primaria (A17): revisión manual en N10."""

    claim_index: int  # posición en `Synthesis.key_claims`
    claim_text: str
    paper_id: str
    chunk_ids: list[str]
    real_author: str
    attribution_note: str


class DraftAudit(BaseModel):
    """Auditoría del borrador de un Experto (`_draft/{expert_id}.json`). Modelo interno, no es contrato."""

    expert_id: str
    run_id: str
    synthesis_id: str
    created_at: datetime
    llm_provider: str
    llm_model: str
    n_candidates: int
    n_proposed: int
    n_kept: int
    discarded: list[DiscardedClaim]
    primary_work_flags: list[PrimaryWorkFlag]


class DraftResult(NamedTuple):
    synthesis: Synthesis
    audit: DraftAudit


class NoValidClaimsError(ValueError):
    """Ninguna claim del borrador sobrevivió a la validación: no hay síntesis que guardar."""


def build_draft_prompt(
    label: ClusterLabel,
    candidates: Sequence[ScoredChunk],
    excavador_storage: PaperLookup,
    primary_works: Mapping[str, PrimaryWork] = PRIMARY_WORKS,
) -> tuple[str, str]:
    """(system, user) para redactar la síntesis. Cada pasaje lleva `chunk_id`, `paper_id`, autor,
    año y fuente (PDF o abstract). Para la obra primaria, el `real_author` sustituye a `authors`
    y va acompañado de su `attribution_note`."""
    system = f"""Eres un investigador que redacta la síntesis de un grupo temático de papers sobre
la obra de Bolívar Echeverría, usando SOLO los pasajes que se te dan.

Produces dos cosas.

1. key_claims: entre {N_MIN_CLAIMS} y {N_MAX_CLAIMS} afirmaciones atómicas (una idea cada una), en español.
- supporting_chunks: uno o más chunk_id copiados exactamente como aparecen entre corchetes.
  Está prohibido citar un id que no esté en la lista; no inventes ni modifiques ids. Si
  ningún pasaje sustenta una afirmación, no la escribas.
- Atribución por autoría, no por tema. Cada pasaje indica su autor. El corpus contiene obra
  primaria de otros autores (traducciones, textos de Marx) y entrevistas. Un pasaje escrito
  por X sustenta lo que X dice, o lo que X expone que otro sostiene. Una afirmación sobre lo
  que piensa Echeverría necesita un pasaje de Echeverría o de un autor que expone a
  Echeverría; un pasaje de Marx no sustenta lo que piensa Echeverría. Si el autor del pasaje
  no es quien la afirmación dice, no lo uses como sustento. Si un pasaje trae una nota de
  atribución, síguela. Nombra en la afirmación a quién atribuyes cada tesis.
- stance: cómo se relacionan los pasajes citados con la afirmación, juzgado leyendo cada pasaje.
    supports: el pasaje sostiene o expone la afirmación.
    contradicts: el pasaje discute, matiza o rechaza la tesis de la afirmación.
    mentions: el pasaje solo la nombra o alude a ella, sin desarrollarla.
  No asumas supports por defecto. Todos los pasajes de una afirmación deben tener la misma
  postura respecto de ella; si difieren, sepáralos en afirmaciones distintas.
- Tesis discutidas (obligatorio). Cuando un pasaje discute, matiza o rechaza una tesis
  (de Echeverría o de otro autor), emite DOS afirmaciones con el mismo texto de tesis:
    a) la tesis, citando los pasajes que la exponen, con stance supports;
    b) la misma tesis, citando los pasajes que la discuten, con stance contradicts.
  El texto de ambas atribuye la tesis a quien la sostiene y termina nombrando, entre
  paréntesis, a los autores de los pasajes citados. Por ejemplo:
    «Echeverría sostiene que T (pasajes de Ana Pérez).» — supports
    «Echeverría sostiene que T (pasajes de Luis Gil).» — contradicts
  El disenso va en stance, no en la frase: está prohibido escribir «Luis Gil critica /
  objeta / discute que T» con supports. Si ningún pasaje expone la tesis discutida, emite
  solo la afirmación con contradicts.
- Si un pasaje de PDF y uno de abstract sustentan lo mismo, cita el de PDF.
- No uses pasajes sin sentido gramatical (texto roto por saltos de página, leyendas de
  diagramas aplanadas, listas de referencias).
- El orden de los pasajes no indica su relevancia.

2. summary: entre 300 y 800 palabras de prosa académica en español que articula las
   afirmaciones. No dice nada que no esté sustentado en key_claims y no incluye ids.

Responde con un objeto JSON con las claves "summary" (cadena) y "key_claims" (lista de
objetos con "text", "supporting_chunks" y "stance")."""

    lines = [
        f"Tema del grupo: {label.topic_label}",
        f"Descripción: {label.one_liner}",
        "",
        f"Pasajes ({len(candidates)}):",
    ]
    for sc in candidates:
        paper_id = sc.chunk.paper_id
        paper = excavador_storage.get_paper(paper_id)
        if paper is None:
            raise ValueError(f"{paper_id} no está en excavador.db")
        primary = primary_works.get(paper_id)
        author = primary.real_author if primary else ("; ".join(paper.authors) or "desconocido")
        source = "abstract" if sc.from_abstract else "PDF"
        lines += ["", f"[{sc.chunk.chunk_id}]", f"paper_id: {paper_id} · autor: {author} · año: {paper.year} · fuente: {source}"]
        if primary:
            lines.append(f"nota de atribución: {primary.attribution_note}")
        lines.append(_clean(sc.chunk.text))
    return system, "\n".join(lines)


def validate_claims(
    drafts: Sequence[ClaimDraft], allowed_chunk_ids: set[str]
) -> tuple[list[Claim], list[DiscardedClaim]]:
    """Separa las claims válidas (C3, ids ⊆ recuperados) de las descartadas, con su motivo. No repara ninguna (X3)."""
    kept: list[Claim] = []
    discarded: list[DiscardedClaim] = []
    for draft in drafts:
        foreign = [chunk_id for chunk_id in draft.supporting_chunks if chunk_id not in allowed_chunk_ids]
        if foreign:
            discarded.append(DiscardedClaim(claim=draft, reason=f"chunk_id fuera de los recuperados: {foreign}"))
            continue
        if not draft.text.strip():
            discarded.append(DiscardedClaim(claim=draft, reason="texto vacío"))
            continue
        try:
            kept.append(Claim(text=draft.text, supporting_chunks=draft.supporting_chunks, stance=draft.stance))
        except ValidationError as exc:
            reasons = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
            discarded.append(DiscardedClaim(claim=draft, reason=f"no valida contra C3: {reasons}"))
    return kept, discarded


def flag_primary_works(
    claims: Sequence[Claim], chunk_paper: Mapping[str, str], primary_works: Mapping[str, PrimaryWork] = PRIMARY_WORKS
) -> list[PrimaryWorkFlag]:
    """Una marca por (claim, paper de obra primaria que cita)."""
    flags = []
    for index, claim in enumerate(claims):
        by_paper: dict[str, list[str]] = {}
        for chunk_id in claim.supporting_chunks:
            paper_id = chunk_paper[chunk_id]
            if paper_id in primary_works:
                by_paper.setdefault(paper_id, []).append(chunk_id)
        for paper_id, chunk_ids in by_paper.items():
            primary = primary_works[paper_id]
            flags.append(
                PrimaryWorkFlag(
                    claim_index=index,
                    claim_text=claim.text,
                    paper_id=paper_id,
                    chunk_ids=chunk_ids,
                    real_author=primary.real_author,
                    attribution_note=primary.attribution_note,
                )
            )
    return flags


def draft_claims(
    expert_id: str,
    label: ClusterLabel,
    candidates: Sequence[ScoredChunk],
    llm_client: LLMClient,
    *,
    run_id: str,
    paper_ids: Sequence[str],
    excavador_storage: PaperLookup,
    primary_works: Mapping[str, PrimaryWork] = PRIMARY_WORKS,
) -> DraftResult:
    """Una llamada al LLM: `Synthesis` (C3) de `expert_id` con las claims que sobreviven a la
    validación, y su auditoría (descartadas con motivo, marcas de obra primaria).

    `paper_ids` es la partición del Experto (el «corpus que cubre» de C3), no solo los
    papers citados. Levanta `NoValidClaimsError` si no sobrevive ninguna claim.
    """
    if not candidates:
        raise ValueError(f"{expert_id} no tiene chunks candidatos")
    system, user = build_draft_prompt(label, candidates, excavador_storage, primary_works)
    context = {"task": "synthesis.draft", "expert_id": expert_id, "run_id": run_id}
    output = llm_client.complete_json(system, user, DraftOutput, context=context)

    chunk_paper = {sc.chunk.chunk_id: sc.chunk.paper_id for sc in candidates}
    kept, discarded = validate_claims(output.key_claims, set(chunk_paper))
    for item in discarded:
        logger.warning("%s: claim descartada (%s): %s", expert_id, item.reason, item.claim.text[:120])
    if not kept:
        raise NoValidClaimsError(
            f"{expert_id}: ninguna de las {len(output.key_claims)} claims sobrevivió: "
            + "; ".join(item.reason for item in discarded)
        )

    updated_at = datetime.now(timezone.utc)
    synthesis = Synthesis(
        synthesis_id=f"{run_id}/{expert_id}/{updated_at:%Y%m%dT%H%M%SZ}",
        expert_id=expert_id,
        topic_label=label.topic_label,
        summary=output.summary,
        key_claims=kept,
        paper_ids=list(paper_ids),
        updated_at=updated_at,
    )
    audit = DraftAudit(
        expert_id=expert_id,
        run_id=run_id,
        synthesis_id=synthesis.synthesis_id,
        created_at=updated_at,
        llm_provider=str(getattr(llm_client, "provider", "unknown")),
        llm_model=str(getattr(llm_client, "model", "unknown")),
        n_candidates=len(candidates),
        n_proposed=len(output.key_claims),
        n_kept=len(kept),
        discarded=discarded,
        primary_work_flags=flag_primary_works(kept, chunk_paper, primary_works),
    )
    return DraftResult(synthesis, audit)


def draft_audit_path(expert_id: str, *, synthesis_dir: Path) -> Path:
    """`{synthesis_dir}/_draft/{expert_id}.json`."""
    return _synthesis_path(Path(synthesis_dir) / DRAFT_SUBDIR, expert_id)


def save_draft_audit(audit: DraftAudit, *, synthesis_dir: Path) -> Path:
    path = draft_audit_path(audit.expert_id, synthesis_dir=synthesis_dir)
    _atomic_write_text(path, audit.model_dump_json(indent=2) + "\n")
    return path


def load_draft_audit(expert_id: str, *, synthesis_dir: Path) -> DraftAudit | None:
    path = draft_audit_path(expert_id, synthesis_dir=synthesis_dir)
    if not path.exists():
        return None
    return DraftAudit.model_validate_json(path.read_text(encoding="utf-8"))


def run_expert_draft(
    expert_id: str,
    llm_client: LLMClient,
    *,
    run_id: str,
    label: ClusterLabel,
    excavador_storage: PaperLookup,
    synthesis_dir: Path,
    out_dir: Path | None = None,
) -> DraftResult:
    """N8 completo para un Experto: lee `_retrieval/` de `synthesis_dir`, redacta (1 llamada) y
    guarda la síntesis y su auditoría en `out_dir` (por defecto, `synthesis_dir`).

    `out_dir` aparte permite comparar modelos sobre el mismo retrieval sin pisar la síntesis de
    producción. Si el LLM falla o no sobrevive ninguna claim, no se escribe nada.
    """
    record = load_retrieval(expert_id, synthesis_dir=synthesis_dir)
    if record is None:
        raise FileNotFoundError(f"falta {retrieval_path(expert_id, synthesis_dir=synthesis_dir)} (correr N7)")
    if record.run_id != run_id:
        raise ValueError(f"{expert_id}: el retrieval es de {record.run_id}, no de {run_id}")
    result = draft_claims(
        expert_id,
        label,
        record.candidates,
        llm_client,
        run_id=run_id,
        paper_ids=record.paper_ids,
        excavador_storage=excavador_storage,
    )
    out_dir = synthesis_dir if out_dir is None else out_dir
    save_synthesis(result.synthesis, synthesis_dir=out_dir)
    save_draft_audit(result.audit, synthesis_dir=out_dir)
    return result
