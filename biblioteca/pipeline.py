"""Orquesta la indexación completa del corpus: PDF/TEI o abstract → chunks → embeddings → Chroma.

Por cada `PaperRecord` de `excavador/storage.py` intenta la ruta con PDF
(GROBID + parseo TEI); si no hay PDF, o si GROBID/el parseo fallan, cae a la
ruta de abstract (P6) sin abortar la corrida. Los embeddings se calculan por
lotes pequeños (F4: WSL con 5.7 GB de RAM totales, ver
`docs/03-REGISTRO-CONSIDERACIONES-BIBLIOTECA_v15.md`) para no cargar toda la
colección en memoria de golpe. Un paper nunca detiene la corrida: cualquier
excepción inesperada se registra con traceback y se cuenta en `papers_failed`.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from biblioteca.abstract_chunker import chunk_from_abstract, plain_text_for_abstract
from biblioteca.chunker import chunk_sections
from biblioteca.config import Settings
from biblioteca.embedder import Embedder, get_embedder
from biblioteca.grobid import GrobidClient, GrobidError
from biblioteca.models import Chunk, IndexStats
from biblioteca.store import ChunkStore
from biblioteca.tei_parser import GrobidParseError, parse_document, save_plain_text
from excavador.models import PaperRecord
from excavador.storage import Storage

logger = logging.getLogger(__name__)

_PROGRESS_EVERY = 10


def index_corpus(
    settings: Settings,
    *,
    force: bool = False,
    limit: int | None = None,
    batch_size: int = 32,
    grobid: GrobidClient | None = None,
    store: ChunkStore | None = None,
    embedder: Embedder | None = None,
) -> IndexStats:
    """Indexa todo el corpus de `Storage(settings.db_path)` en `store` (Chroma).

    Por cada paper: si ya está indexado y `force` es False, se omite
    (`papers_skipped`); con `force=True` se borra primero y se reindexa. Si
    tiene PDF existente, se procesa con GROBID + TEI; si GROBID o el parseo
    fallan, se cae a la ruta de abstract sin abortar la corrida (se cuenta en
    `papers_failed` pero el paper queda indexado igual). Sin PDF, se indexa
    directo desde título+abstract. Los embeddings se calculan en lotes de
    `batch_size`. `grobid`, `store` y `embedder` son inyectables (tests); si
    son `None` se construyen desde `settings`.
    """
    if grobid is None:
        grobid = GrobidClient(settings.grobid_url, settings.tei_dir)
    if store is None:
        store = ChunkStore(settings.chroma_dir)
    if embedder is None:
        embedder = get_embedder(settings.embedding_model)

    started_at = time.monotonic()

    papers = Storage(settings.db_path).all_papers()
    if limit is not None:
        papers = papers[:limit]

    stats = {
        "papers_total": len(papers),
        "papers_indexed": 0,
        "papers_skipped": 0,
        "papers_failed": 0,
        "chunks_created": 0,
        "from_abstract_count": 0,
    }

    for n, paper in enumerate(papers, start=1):
        try:
            _index_one_paper(paper, settings, force, batch_size, grobid, store, embedder, stats)
        except Exception:
            logger.exception("Fallo inesperado indexando %s, se continúa con el resto", paper.paper_id)
            stats["papers_failed"] += 1

        if n % _PROGRESS_EVERY == 0:
            logger.info(
                "Progreso: %d/%d papers procesados (indexados=%d, saltados=%d, fallidos=%d)",
                n,
                stats["papers_total"],
                stats["papers_indexed"],
                stats["papers_skipped"],
                stats["papers_failed"],
            )

    duration_s = time.monotonic() - started_at
    return IndexStats(duration_s=duration_s, **stats)


def _index_one_paper(
    paper: PaperRecord,
    settings: Settings,
    force: bool,
    batch_size: int,
    grobid: GrobidClient,
    store: ChunkStore,
    embedder: Embedder,
    stats: dict[str, int],
) -> None:
    """Procesa un único paper y actualiza `stats` in-place (extraído para el try/except por paper)."""
    if store.has_paper(paper.paper_id):
        if not force:
            stats["papers_skipped"] += 1
            return
        store.delete_paper(paper.paper_id)

    chunks, from_abstract, grobid_failed = _build_chunks(paper, settings, grobid)
    if grobid_failed:
        stats["papers_failed"] += 1

    if not chunks:
        stats["papers_skipped"] += 1
        logger.info("Paper %s sin contenido citable, se omite", paper.paper_id)
        return

    _embed_and_store(chunks, from_abstract, batch_size, store, embedder)

    stats["papers_indexed"] += 1
    stats["chunks_created"] += len(chunks)
    if from_abstract:
        stats["from_abstract_count"] += len(chunks)

    route = "abstract" if from_abstract else "pdf"
    logger.info("Paper %s indexado (ruta=%s, chunks=%d)", paper.paper_id, route, len(chunks))


def _build_chunks(
    paper: PaperRecord, settings: Settings, grobid: GrobidClient
) -> tuple[list[Chunk], bool, bool]:
    """Devuelve `(chunks, from_abstract, grobid_failed)` para `paper`.

    Intenta la ruta PDF si `paper.pdf_path` existe en disco; si GROBID o el
    parseo del TEI fallan, cae a la ruta de abstract (`grobid_failed=True`)
    en vez de abortar. Sin PDF utilizable, indexa directo desde abstract.
    """
    pdf_path = Path(paper.pdf_path) if paper.pdf_path else None
    if pdf_path is not None and pdf_path.exists():
        try:
            tei_path = grobid.process_fulltext(pdf_path)
            doc = parse_document(tei_path)
            save_plain_text(doc, paper.paper_id, settings.text_dir)
            chunks = chunk_sections(
                sections=doc.sections,
                full_text=doc.full_text,
                paper_id=paper.paper_id,
                embedding_model=settings.embedding_model,
                min_tokens=settings.chunk_min_tokens,
                max_tokens=settings.chunk_max_tokens,
            )
            return chunks, False, False
        except (GrobidError, GrobidParseError):
            logger.error(
                "GROBID o el parseo fallaron para %s, se recurre a abstract", paper.paper_id
            )
            grobid_failed = True
    else:
        grobid_failed = False

    text = plain_text_for_abstract(paper)
    _save_abstract_plain_text(text, paper.paper_id, settings.text_dir)
    chunks = chunk_from_abstract(
        paper, embedding_model=settings.embedding_model, max_tokens=settings.chunk_max_tokens
    )
    return chunks, True, grobid_failed


def _save_abstract_plain_text(text: str, paper_id: str, text_dir: Path) -> Path:
    """Persiste el texto de título+abstract en `text_dir`, igual que `save_plain_text` con PDFs (P8)."""
    text_dir.mkdir(parents=True, exist_ok=True)
    sanitized_id = paper_id.replace(":", "_").replace("/", "_")
    out_path = text_dir / f"{sanitized_id}.txt"
    out_path.write_text(text, encoding="utf-8")
    return out_path


def _embed_and_store(
    chunks: list[Chunk], from_abstract: bool, batch_size: int, store: ChunkStore, embedder: Embedder
) -> None:
    """Embebe y guarda `chunks` en lotes de `batch_size` (F4: RAM limitada)."""
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        embeddings = embedder.embed_passages([chunk.text for chunk in batch])
        store.upsert_chunks(batch, embeddings, from_abstract=from_abstract)
