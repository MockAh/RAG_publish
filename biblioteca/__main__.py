"""CLI de la Biblioteca (M16).

Uso:
    python -m biblioteca index [--force] [--limit N] [--batch-size 32]
    python -m biblioteca query "TEXTO" [--top-k 5] [--paper-id X] [--section S]
    python -m biblioteca stats
    python -m biblioteca get CHUNK_ID
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import typer

from biblioteca.config import Settings
from biblioteca.models import IndexStats
from biblioteca.pipeline import index_corpus
from biblioteca.store import ChunkStore
from excavador.storage import Storage

app = typer.Typer()

_INDEX_STATS_LABELS: dict[str, str] = {
    "papers_total": "Papers totales",
    "papers_indexed": "Papers indexados",
    "papers_skipped": "Papers omitidos",
    "papers_failed": "Papers fallidos",
    "chunks_created": "Chunks creados",
    "from_abstract_count": "Chunks desde abstract",
    "duration_min": "Duración",
}


_NOISY_LOGGERS = (
    "httpx",
    "httpcore",
    "huggingface_hub",
    "sentence_transformers",
    "transformers",
    "urllib3",
    "chromadb",
)


def _configure_logging() -> Path:
    """Configura logging a INFO con timestamp, a consola y a `data/logs/index_<fecha>.log` (corrida desatendida y larga, M16)."""
    log_dir = Path("data/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"index_{datetime.now():%Y%m%d_%H%M%S}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_path, encoding="utf-8")],
        force=True,
    )
    for logger_name in _NOISY_LOGGERS:  # silencia el ruido de descarga del modelo (corrida desatendida)
        logging.getLogger(logger_name).setLevel(logging.WARNING)
    return log_path


def _print_index_header(settings: Settings) -> None:
    """Imprime papers en la DB, cuántos con PDF, y el directorio de Chroma (última chance de ver que se apunta a la DB equivocada)."""
    papers = Storage(settings.db_path).all_papers()
    with_pdf = sum(1 for paper in papers if paper.pdf_path is not None)
    typer.echo(f"Papers en {settings.db_path}: {len(papers)} (con PDF: {with_pdf})")
    typer.echo(f"Directorio de Chroma: {settings.chroma_dir}")


def _format_index_stat(field: str, stats: IndexStats) -> str:
    """Formatea un campo de `IndexStats`; `duration_min` se deriva de `duration_s`."""
    if field == "duration_min":
        return f"{stats.duration_s / 60:.1f} min"
    return str(getattr(stats, field))


def _print_index_stats(stats: IndexStats) -> None:
    """Imprime `IndexStats` como tabla legible, con la duración en minutos."""
    rows = [(label, _format_index_stat(field, stats)) for field, label in _INDEX_STATS_LABELS.items()]
    width = max(len(label) for label, _ in rows)
    typer.echo(f"\n{'Métrica':<{width}}  Valor")
    typer.echo(f"{'-' * width}  {'-' * 5}")
    for label, value in rows:
        typer.echo(f"{label:<{width}}  {value}")


@app.command()
def index(
    force: bool = typer.Option(False, "--force", help="Reindexa papers que ya estaban indexados."),
    limit: int | None = typer.Option(None, "--limit", help="Tope de papers a procesar."),
    batch_size: int = typer.Option(32, "--batch-size", help="Tamaño de lote para embeber."),
) -> None:
    """Indexa el corpus completo: PDF/TEI o abstract → chunks → embeddings → Chroma."""
    settings = Settings()

    _print_index_header(settings)
    log_path = _configure_logging()
    typer.echo(f"Log de esta corrida: {log_path}\n")

    stats = index_corpus(settings, force=force, limit=limit, batch_size=batch_size)

    _print_index_stats(stats)


@app.command()
def query(
    texto: str = typer.Argument(..., help="Texto de la consulta."),
    top_k: int = typer.Option(5, "--top-k", help="Número de resultados a devolver."),
    paper_id: list[str] = typer.Option([], "--paper-id", help="Filtra por paper_id (repetible)."),
    section: list[str] = typer.Option([], "--section", help="Filtra por sección (repetible)."),
) -> None:
    """Busca los chunks más similares a `texto` en Chroma."""
    settings = Settings()
    store = ChunkStore(settings.chroma_dir)

    resultados = store.retrieve(
        texto,
        top_k=top_k,
        filter_paper_ids=paper_id or None,
        filter_sections=section or None,
    )

    if not resultados:
        typer.echo("Sin resultados para esta consulta.")
        return

    for posicion, scored in enumerate(resultados, start=1):
        marca = " [abstract]" if scored.from_abstract else ""
        typer.echo(f"{posicion}. score={scored.score:.3f}{marca}  {scored.chunk.chunk_id}")
        typer.echo(f"   {scored.chunk.text[:300]}")


@app.command()
def stats() -> None:
    """Resume la colección de Chroma: chunks totales, papers distintos, from_abstract y media por paper."""
    settings = Settings()
    store = ChunkStore(settings.chroma_dir)

    total_chunks = store.count()
    if total_chunks == 0:
        typer.echo(f"La colección de Chroma en {settings.chroma_dir} está vacía.")
        return

    metadatas = store.all_metadata()
    paper_ids = {metadata["paper_id"] for metadata in metadatas}
    from_abstract = sum(1 for metadata in metadatas if metadata["from_abstract"])

    typer.echo(f"Chunks totales: {total_chunks}")
    typer.echo(f"Papers distintos indexados: {len(paper_ids)}")
    typer.echo(f"Chunks desde abstract: {from_abstract}")
    typer.echo(f"Media de chunks por paper: {total_chunks / len(paper_ids):.1f}")


@app.command()
def get(chunk_id: str = typer.Argument(..., help="chunk_id a inspeccionar.")) -> None:
    """Imprime el chunk completo (C2 + from_abstract), herramienta de auditoría manual (criterio 4, muestreo D5)."""
    settings = Settings()
    store = ChunkStore(settings.chroma_dir)

    encontrado = store.get_chunk_full(chunk_id)
    if encontrado is None:
        typer.echo(f"No existe ningún chunk con chunk_id={chunk_id!r}.")
        raise typer.Exit(code=1)

    chunk, from_abstract = encontrado
    typer.echo(f"chunk_id: {chunk.chunk_id}")
    typer.echo(f"paper_id: {chunk.paper_id}")
    typer.echo(f"section: {chunk.section}")
    typer.echo(f"char_start: {chunk.char_start}")
    typer.echo(f"char_end: {chunk.char_end}")
    typer.echo(f"embedding_model: {chunk.embedding_model}")
    typer.echo(f"from_abstract: {from_abstract}")
    typer.echo("text:")
    typer.echo(chunk.text)


if __name__ == "__main__":
    app()
