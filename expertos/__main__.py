"""CLI de Expertos.

Uso:
    python -m expertos vectors build
    python -m expertos cluster sweep
    python -m expertos cluster inspect --k 9
    python -m expertos cluster assign --k 9
"""

from __future__ import annotations

import logging

import typer

from biblioteca.config import Settings as BibliotecaSettings
from biblioteca.embedder import get_embedder
from biblioteca.store import ChunkStore
from expertos.assignments import labels_to_assignment, make_run_id, save_assignment
from expertos.clustering import load_matrix, report, run_hdbscan, sweep_kmeans
from expertos.config import Settings
from expertos.inspection import dump_clusters
from expertos.vectors import (
    build_representative_vectors,
    get_indexed_paper_ids,
    load_vectors,
    save_vectors,
)
from excavador.storage import Storage

app = typer.Typer()
vectors_app = typer.Typer()
app.add_typer(vectors_app, name="vectors")
cluster_app = typer.Typer()
app.add_typer(cluster_app, name="cluster")

_NOISY_LOGGERS = (
    "httpx",
    "httpcore",
    "huggingface_hub",
    "sentence_transformers",
    "transformers",
    "urllib3",
    "chromadb",
)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=True
    )
    for logger_name in _NOISY_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


@vectors_app.command("build")
def vectors_build() -> None:
    """Genera un vector representativo por paper indexado y lo guarda en `expert_vectors_path`."""
    _configure_logging()
    settings = Settings()
    biblioteca_settings = BibliotecaSettings()
    storage = Storage(biblioteca_settings.db_path)
    chunk_store = ChunkStore(biblioteca_settings.chroma_dir)

    paper_ids = get_indexed_paper_ids(biblioteca_settings, excavador_storage=storage, chunk_store=chunk_store)
    embedder = get_embedder(biblioteca_settings.embedding_model)
    vectors = build_representative_vectors(paper_ids, storage, chunk_store, embedder)
    save_vectors(vectors, settings.expert_vectors_path)

    dim = len(next(iter(vectors.values()))) if vectors else 0
    typer.echo(f"{len(vectors)} vectores (dim {dim}) → {settings.expert_vectors_path}")


@cluster_app.command("sweep")
def cluster_sweep() -> None:
    """Barrido k-means (k = 5–12) + HDBSCAN sobre `expert_vectors_path`; informe en `cluster_report_path`."""
    _configure_logging()
    settings = Settings()
    X, paper_ids = load_matrix(load_vectors(settings.expert_vectors_path))
    sweep = sweep_kmeans(X)
    hdbscan = run_hdbscan(X)
    report(sweep, hdbscan, paper_ids, settings.cluster_report_path)
    typer.echo(
        f"{len(paper_ids)} papers, k = {sweep[0].k}–{sweep[-1].k}, "
        f"HDBSCAN: {hdbscan.n_clusters} clústeres + {hdbscan.n_noise} ruido → {settings.cluster_report_path}"
    )


@cluster_app.command("inspect")
def cluster_inspect(k: int = typer.Option(..., "--k", help="Número de clústeres a inspeccionar.")) -> None:
    """Vuelca los papers más cercanos al centroide de cada clúster en `cluster_inspect_dir/cluster_inspect_k{k}.md`."""
    _configure_logging()
    settings = Settings()
    X, paper_ids = load_matrix(load_vectors(settings.expert_vectors_path))
    out_path = settings.cluster_inspect_dir / f"cluster_inspect_k{k}.md"
    dump_clusters(X, paper_ids, k, Storage(settings.db_path), out_path)
    typer.echo(f"{len(paper_ids)} papers, k={k} → {out_path}")


@cluster_app.command("assign")
def cluster_assign(
    k: int = typer.Option(..., "--k", help="k elegido en N4."),
    seed: int = typer.Option(42, "--seed"),
) -> None:
    """Persiste la asignación paper → experto del k elegido en la tabla `clusters` (X5)."""
    _configure_logging()
    settings = Settings()
    X, paper_ids = load_matrix(load_vectors(settings.expert_vectors_path))
    [result] = sweep_kmeans(X, k_min=k, k_max=k, seed=seed)
    run_id = make_run_id(k, seed, settings.expert_vectors_path)
    save_assignment(settings.db_path, run_id, labels_to_assignment(paper_ids, result.labels))
    sizes = ", ".join(f"C{c}={n}" for c, n in sorted(result.sizes.items(), key=lambda item: -item[1]))
    typer.echo(f"{len(paper_ids)} papers → clusters[run_id={run_id}] en {settings.db_path}: {sizes}")


if __name__ == "__main__":
    app()
