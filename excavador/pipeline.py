"""Pipeline completo del Excavador (T11): busca, normaliza, dedupea, puntúa,
expande por snowballing, enriquece, descarga PDFs y persiste.

Orden de dependencias con T3-T10: ver `docs/02-PLAN-IMPLEMENTACION-EXCAVADOR.md`.
"""

import logging
import re
import time
from datetime import datetime, timezone

import httpx
from pydantic import BaseModel

from excavador.apis.crossref import CrossrefClient
from excavador.apis.openalex import OpenAlexClient
from excavador.apis.semanticscholar import SemanticScholarClient
from excavador.config import Settings
from excavador.dedup import dedup, normalize_doi, normalize_title
from excavador.download import download_pdf
from excavador.models import DiscardedRecord, PaperRecord, RawHit
from excavador.normalize import (
    canonical_enrich,
    normalize_crossref,
    normalize_openalex,
    normalize_semanticscholar,
)
from excavador.relevance import RelevanceScorer
from excavador.snowball import snowball
from excavador.storage import Storage

logger = logging.getLogger(__name__)

_PHRASE_RE = re.compile(r'"([^"]+)"|«([^»]+)»')

_NORMALIZERS = {
    "openalex": normalize_openalex,
    "crossref": normalize_crossref,
    "semanticscholar": normalize_semanticscholar,
}


class PipelineStats(BaseModel):
    """Conteos y métricas de una corrida completa del pipeline."""

    raw_hits: int
    invalid: int
    duplicates: int
    low_relevance: int
    snowball_raw_hits: int
    accepted: int
    with_pdf: int
    pct_pdf: float
    pct_doi: float
    duration_s: float


def _extract_phrases(tema: str) -> list[str]:
    """Frases entre comillas dobles rectas o «» latinas; el tema entero si no hay."""
    matches = _PHRASE_RE.findall(tema)
    phrases = [straight or latin for straight, latin in matches]
    return phrases if phrases else [tema]


def _paper_id_for_hit(hit: RawHit) -> str:
    """Regla T5: `"doi:<doi>"` si el hit tiene DOI; si no, `"<source_api>:<external_id>"`."""
    if hit.doi:
        return f"doi:{hit.doi.strip().lower()}"
    return f"{hit.source_api}:{hit.external_id}"


def _dedup_key(record: PaperRecord) -> tuple:
    """Misma clave de agrupación que `dedup._group_key` (T6), replicada aquí
    para poder comparar contra los ya aceptados en esta misma corrida."""
    if record.doi:
        return ("doi", normalize_doi(record.doi))
    return ("title", normalize_title(record.title), record.year)


def _invalid_record(hit: RawHit) -> DiscardedRecord:
    """Placeholder de `DiscardedRecord` para un RawHit que no normalizó (sin título/año)."""
    return DiscardedRecord(
        paper_id=_paper_id_for_hit(hit),
        doi=hit.doi,
        title=hit.title or "(sin título)",
        authors=[],
        year=0,
        venue=None,
        abstract="",
        source_api=hit.source_api,
        work_type="other",
        pdf_path=None,
        relevance_score=0.0,
        references_ids=[],
        ingested_at=datetime.now(timezone.utc),
        discard_reason="invalid_record",
    )


def _discard(record: PaperRecord, reason: str) -> DiscardedRecord:
    """Copia `record` a `DiscardedRecord` con `discard_reason=reason`."""
    return DiscardedRecord(**record.model_dump(), discard_reason=reason)


def run(
    tema: str,
    max_papers: int,
    settings: Settings,
    *,
    openalex: OpenAlexClient | None = None,
    crossref: CrossrefClient | None = None,
    s2: SemanticScholarClient | None = None,
    scorer: RelevanceScorer | None = None,
    storage: Storage | None = None,
) -> PipelineStats:
    """Ejecuta el pipeline completo (T11) y devuelve `PipelineStats`."""
    start = time.monotonic()

    openalex = openalex if openalex is not None else OpenAlexClient(mailto=settings.openalex_mailto)
    crossref = crossref if crossref is not None else CrossrefClient(mailto=settings.openalex_mailto)
    s2 = s2 if s2 is not None else SemanticScholarClient(api_key=settings.semanticscholar_api_key)
    scorer = scorer if scorer is not None else RelevanceScorer(settings.embedding_model)
    storage = storage if storage is not None else Storage(settings.db_path)

    # a. Búsqueda: OpenAlex es imprescindible, su fallo propaga; crossref/s2 son opcionales.
    hits: list[RawHit] = list(openalex.search(tema))
    for phrase in _extract_phrases(tema):
        hits.extend(openalex.search_exact_phrase(phrase))

    try:
        hits.extend(crossref.search(tema))
    except Exception as exc:  # noqa: BLE001 - una fuente opcional no puede tumbar el pipeline
        logger.warning("Crossref search falló, se continúa sin esa fuente: %s", exc)

    try:
        hits.extend(s2.search(tema))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Semantic Scholar search falló, se continúa sin esa fuente: %s", exc)

    raw_hits_count = len(hits)
    logger.info("Búsqueda: %d RawHits recolectados", raw_hits_count)

    raws: dict[str, dict] = {}
    accepted: list[PaperRecord] = []
    discarded: list[DiscardedRecord] = []
    accepted_keys: set[tuple] = set()
    known_dois = storage.known_dois()

    counters = {"invalid": 0, "duplicates": 0, "low_relevance": 0}

    def _process(batch_hits: list[RawHit]) -> None:
        """Repite los pasos b-d (normalizar, dedup+filtro DB, scoring) sobre un lote."""
        normalized: list[PaperRecord] = []
        for hit in batch_hits:
            paper_id = _paper_id_for_hit(hit)
            if paper_id not in raws or hit.source_api == "openalex":
                raws[paper_id] = hit.raw
            record = _NORMALIZERS[hit.source_api](hit)
            if record is None:
                counters["invalid"] += 1
                discarded.append(_invalid_record(hit))
                continue
            normalized.append(record)

        uniques, batch_duplicates = dedup(normalized)
        counters["duplicates"] += len(batch_duplicates)
        discarded.extend(_discard(r, "duplicate") for r in batch_duplicates)

        new_records: list[PaperRecord] = []
        for record in uniques:
            key = _dedup_key(record)
            if key in accepted_keys:
                counters["duplicates"] += 1
                discarded.append(_discard(record, "duplicate"))
                continue
            if record.doi and normalize_doi(record.doi) in known_dois:
                continue  # ya vive en la DB: ni aceptado ni descartado
            if not record.doi and storage.get_paper(record.paper_id) is not None:
                continue  # ya vive en la DB: ni aceptado ni descartado
            new_records.append(record)

        if not new_records:
            return

        scored = scorer.score(tema, new_records)
        keep, drop = RelevanceScorer.split_by_threshold(scored, settings.relevance_threshold)
        counters["low_relevance"] += len(drop)
        discarded.extend(_discard(r, "low_relevance") for r in drop)

        for record in keep:
            accepted.append(record)
            accepted_keys.add(_dedup_key(record))

    _process(hits)
    logger.info(
        "Normalización inicial: %d inválidos, %d duplicados, %d bajo umbral, %d aceptados",
        counters["invalid"],
        counters["duplicates"],
        counters["low_relevance"],
        len(accepted),
    )

    # e. Snowball (una sola pasada: los hits que aporta repiten b-d, sin segundo snowball).
    snowball_hits = snowball(accepted, openalex, settings.snowball_k)
    logger.info("Snowball: %d RawHits nuevos", len(snowball_hits))
    _process(snowball_hits)
    logger.info(
        "Tras snowball: %d inválidos, %d duplicados, %d bajo umbral, %d aceptados (total)",
        counters["invalid"],
        counters["duplicates"],
        counters["low_relevance"],
        len(accepted),
    )

    # f. Enriquecimiento canónico: solo aceptados incompletos, con DOI, que no vengan de OpenAlex.
    for i, record in enumerate(accepted):
        needs_enrich = record.abstract == "" or not record.references_ids
        if needs_enrich and record.doi and record.source_api != "openalex":
            try:
                enriched_hit = openalex.enrich(record.doi)
            except Exception as exc:  # noqa: BLE001 - un enrich caído no puede tumbar el pipeline
                logger.warning(
                    "Enriquecimiento canónico falló para %s: %s", record.paper_id, exc
                )
                continue
            accepted[i] = canonical_enrich(record, enriched_hit)

    # g. Corte por max_papers ANTES de descargar (no desperdiciar descargas).
    accepted.sort(key=lambda r: r.relevance_score, reverse=True)
    accepted = accepted[:max_papers]

    # h. Descarga de PDFs (un solo httpx.Client compartido).
    with httpx.Client() as client:
        for i, record in enumerate(accepted):
            pdf_path = download_pdf(record, raws.get(record.paper_id), settings.pdf_dir, client)
            if pdf_path is not None:
                accepted[i] = record.model_copy(update={"pdf_path": pdf_path})

    # i. Persistencia.
    for record in accepted:
        storage.upsert_paper(record)
    for record in discarded:
        storage.upsert_discarded(record)

    n_accepted = len(accepted)
    with_pdf = sum(1 for r in accepted if r.pdf_path is not None)
    with_doi = sum(1 for r in accepted if r.doi is not None)

    stats = PipelineStats(
        raw_hits=raw_hits_count,
        invalid=counters["invalid"],
        duplicates=counters["duplicates"],
        low_relevance=counters["low_relevance"],
        snowball_raw_hits=len(snowball_hits),
        accepted=n_accepted,
        with_pdf=with_pdf,
        pct_pdf=(with_pdf / n_accepted) if n_accepted else 0.0,
        pct_doi=(with_doi / n_accepted) if n_accepted else 0.0,
        duration_s=time.monotonic() - start,
    )
    logger.info("Pipeline completo: %s", stats.model_dump())
    return stats
