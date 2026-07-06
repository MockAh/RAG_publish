"""CLI del Excavador (T12).

Uso:
    python -m excavador run --tema "..." [--max-papers 300] [--threshold 0.4]
    python -m excavador stats
"""

import logging
import sqlite3

import typer

from excavador.config import Settings
from excavador.pipeline import PipelineStats
from excavador.pipeline import run as pipeline_run
from excavador.storage import Storage

app = typer.Typer()

_STATS_LABELS: dict[str, str] = {
    "raw_hits": "RawHits recolectados",
    "invalid": "Inválidos",
    "duplicates": "Duplicados",
    "low_relevance": "Baja relevancia",
    "snowball_raw_hits": "RawHits de snowball",
    "accepted": "Aceptados",
    "with_pdf": "Con PDF",
    "pct_pdf": "% con PDF",
    "pct_doi": "% con DOI",
    "duration_s": "Duración",
}

_PERCENT_FIELDS = {"pct_pdf", "pct_doi"}


def _format_stat_value(field: str, value: object) -> str:
    if field in _PERCENT_FIELDS:
        return f"{value * 100:.1f} %"
    if field == "duration_s":
        return f"{value:.1f} s"
    return str(value)


def _print_stats(stats: PipelineStats) -> None:
    rows = [
        (label, _format_stat_value(field, getattr(stats, field)))
        for field, label in _STATS_LABELS.items()
    ]
    width = max(len(label) for label, _ in rows)
    typer.echo(f"{'Métrica':<{width}}  Valor")
    typer.echo(f"{'-' * width}  {'-' * 5}")
    for label, value in rows:
        typer.echo(f"{label:<{width}}  {value}")


@app.command()
def run(
    tema: str = typer.Option(..., "--tema", help="Tema de búsqueda (obligatorio)."),
    max_papers: int = typer.Option(300, "--max-papers", help="Tope de papers aceptados."),
    threshold: float | None = typer.Option(
        None, "--threshold", help="Pisa `settings.relevance_threshold` si se indica."
    ),
) -> None:
    """Corre el pipeline completo del Excavador y muestra las PipelineStats resultantes."""
    logging.basicConfig(level=logging.INFO)

    settings = Settings()
    if threshold is not None:
        settings = settings.model_copy(update={"relevance_threshold": threshold})

    stats = pipeline_run(tema, max_papers, settings)
    _print_stats(stats)


@app.command()
def stats() -> None:
    """Muestra un resumen de la base de datos: totales, top-20 y descartes por motivo."""
    settings = Settings()

    if not settings.db_path.exists():
        typer.echo(f"No existe la base de datos en {settings.db_path}. Corre `run` primero.")
        return

    storage = Storage(settings.db_path)
    all_papers = storage.all_papers()
    total = len(all_papers)

    if total == 0:
        typer.echo(f"La base de datos en {settings.db_path} está vacía. Corre `run` primero.")
        return

    with_pdf = sum(1 for p in all_papers if p.pdf_path is not None)
    with_doi = sum(1 for p in all_papers if p.doi is not None)

    typer.echo(f"Total papers: {total}")
    typer.echo(f"Con PDF: {with_pdf / total * 100:.1f} %")
    typer.echo(f"Con DOI: {with_doi / total * 100:.1f} %")

    typer.echo("\nTop 20 por relevance_score:")
    top20 = sorted(all_papers, key=lambda p: p.relevance_score, reverse=True)[:20]
    for p in top20:
        title = p.title if len(p.title) <= 60 else p.title[:60]
        typer.echo(f"{p.relevance_score:.3f}  {p.year}  {title}")

    conn = sqlite3.connect(settings.db_path)
    try:
        cursor = conn.execute(
            "SELECT discard_reason, COUNT(*) FROM papers_discarded GROUP BY discard_reason"
        )
        reason_counts = cursor.fetchall()
    finally:
        conn.close()

    typer.echo("\nDescartados por motivo:")
    if not reason_counts:
        typer.echo("(sin descartes registrados)")
    for reason, count in reason_counts:
        typer.echo(f"{reason}: {count}")


if __name__ == "__main__":
    app()
