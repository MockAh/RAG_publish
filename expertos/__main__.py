"""CLI de Expertos.

Uso:
    python -m expertos vectors build
    python -m expertos cluster sweep
    python -m expertos cluster inspect --k 9
    python -m expertos cluster assign --k 9
    python -m expertos cluster label [--expert-id C8] [--run-id ...]
    python -m expertos cluster merge --from C8 --into C0
    python -m expertos synthesis retrieve [--expert-id C3] [--run-id ...]
    python -m expertos synthesis draft [--expert-id C8] [--force] [--run-id ...] [--out-dir ...]
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import typer

from biblioteca.config import Settings as BibliotecaSettings
from biblioteca.embedder import get_embedder
from biblioteca.store import ChunkStore
from expertos.assignments import (
    labels_to_assignment,
    load_assignment,
    load_corpus_assignment,
    make_run_id,
    merge_clusters,
    save_assignment,
)
from expertos.clustering import load_matrix, report, run_hdbscan, sweep_kmeans
from expertos.config import Settings
from expertos.inspection import dump_clusters
from expertos.labeling import label_all_clusters, label_cluster, load_labels, update_labels
from expertos.llm import LLMOutputError, make_client
from expertos.synthesis import (
    NoValidClaimsError,
    pending_drafts,
    retrieval_path,
    run_expert_draft,
    run_expert_retrieval,
)
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
synthesis_app = typer.Typer()
app.add_typer(synthesis_app, name="synthesis")

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


def _check_run_id_matches_vectors(run_id: str, settings: Settings) -> None:
    """Sale con error si `run_id` no corresponde a `expert_vectors_path`.

    El sufijo del run_id base ata la partición a los vectores (A8): con otros vectores, el centroide
    mentiría. Una corrida derivada (`<base>+merge-…`) hereda el hash de su base.
    """
    vectors_hash = hashlib.sha256(settings.expert_vectors_path.read_bytes()).hexdigest()[:8]
    if not run_id.split("+", 1)[0].endswith(f"-{vectors_hash}"):
        typer.echo(f"{run_id} no corresponde a {settings.expert_vectors_path} (hash {vectors_hash})", err=True)
        raise typer.Exit(1)


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


@cluster_app.command("label")
def cluster_label(
    expert_id: str | None = typer.Option(None, "--expert-id", help="Etiquetar solo este clúster (p. ej. C8)."),
    run_id: str | None = typer.Option(None, "--run-id", help="Por defecto, `cluster_run_id` de Settings."),
) -> None:
    """Etiqueta los clústeres con el LLM (una llamada por clúster) y los guarda en `cluster_labels_path`."""
    _configure_logging()
    settings = Settings()
    run_id = run_id or settings.cluster_run_id
    _check_run_id_matches_vectors(run_id, settings)

    context = dict(
        run_id=run_id,
        vectors=load_vectors(settings.expert_vectors_path),
        db_path=settings.db_path,
        excavador_storage=Storage(settings.db_path),
    )
    llm_client = make_client("label", settings)
    if expert_id is None:
        # Guarda tras cada clúster: un 429 de cuota diaria no pierde lo ya etiquetado.
        new_labels = label_all_clusters(llm_client, **context, labels_path=settings.cluster_labels_path)
        expected = set(load_corpus_assignment(settings.db_path, run_id).values())
    else:
        new_labels = {expert_id: label_cluster(expert_id, llm_client, **context)}
        update_labels(settings.cluster_labels_path, run_id, new_labels)
        expected = {expert_id}

    for eid, label in sorted(new_labels.items(), key=lambda item: int(item[0][1:])):
        flag = "" if label.coherent else "  [coherent=False]"
        typer.echo(f"{eid}: {label.topic_label}{flag}")
        typer.echo(f"    {label.one_liner}")
        if label.note:
            typer.echo(f"    note: {label.note}")
    missing = sorted(expected - new_labels.keys(), key=lambda e: int(e[1:]))
    typer.echo(f"{len(new_labels)} etiquetas nuevas → {settings.cluster_labels_path} [{run_id}]")
    if missing:
        typer.echo(f"Sin etiqueta (reintentar con --expert-id): {', '.join(missing)}", err=True)
        raise typer.Exit(1)


@cluster_app.command("merge")
def cluster_merge(
    source: str = typer.Option(..., "--from", help="Clúster que desaparece (p. ej. C8)."),
    target: str = typer.Option(..., "--into", help="Clúster que lo absorbe (p. ej. C0)."),
    run_id: str | None = typer.Option(None, "--run-id", help="Por defecto, `cluster_run_id` de Settings."),
) -> None:
    """Guarda en `clusters` una corrida derivada `<run_id>+merge-<from>-<into>`; la de origen no se toca."""
    _configure_logging()
    settings = Settings()
    run_id = run_id or settings.cluster_run_id
    derived = merge_clusters(settings.db_path, run_id, source, target)
    corpus = load_corpus_assignment(settings.db_path, derived)
    n_target = sum(1 for eid in load_assignment(settings.db_path, derived).values() if eid == target)
    n_corpus = sum(1 for eid in corpus.values() if eid == target)
    typer.echo(
        f"{derived}: {len(set(corpus.values()))} clústeres; {target} = {n_target} papers "
        f"({n_corpus} tras la stoplist)"
    )


@synthesis_app.command("retrieve")
def synthesis_retrieve(
    expert_id: str | None = typer.Option(None, "--expert-id", help="Procesar solo este clúster (p. ej. C3)."),
    run_id: str | None = typer.Option(None, "--run-id", help="Por defecto, `cluster_run_id` de Settings."),
) -> None:
    """Sub-consultas (1 llamada LLM por clúster) y retrieval sobre la partición → `synthesis_dir/_retrieval/`.

    Sin `--expert-id`, omite los clústeres que ya tienen archivo de retrieval (reanudar tras un fallo
    gasta solo las llamadas que faltan); con `--expert-id`, lo regenera siempre.
    """
    _configure_logging()
    settings = Settings()
    run_id = run_id or settings.cluster_run_id
    _check_run_id_matches_vectors(run_id, settings)

    labels = load_labels(settings.cluster_labels_path, run_id)
    expected = sorted(set(load_corpus_assignment(settings.db_path, run_id).values()), key=lambda e: int(e[1:]))
    if expert_id is not None:
        if expert_id not in expected:
            typer.echo(f"{expert_id} no está en clusters[run_id={run_id}]", err=True)
            raise typer.Exit(1)
        todo = [expert_id]
    else:
        todo = [eid for eid in expected if not retrieval_path(eid, synthesis_dir=settings.synthesis_dir).exists()]
    unlabeled = [eid for eid in todo if eid not in labels]
    if unlabeled:
        typer.echo(f"Sin etiqueta en {settings.cluster_labels_path} [{run_id}]: {', '.join(unlabeled)}", err=True)
        raise typer.Exit(1)

    llm_client = make_client("synthesis", settings)
    chunk_store = ChunkStore(settings.chroma_dir)
    context = dict(
        run_id=run_id,
        vectors=load_vectors(settings.expert_vectors_path),
        db_path=settings.db_path,
        excavador_storage=Storage(settings.db_path),
        synthesis_dir=settings.synthesis_dir,
    )
    failed = []
    for eid in todo:
        try:
            record = run_expert_retrieval(eid, llm_client, chunk_store, label=labels[eid], **context)
        except LLMOutputError as exc:
            logging.getLogger(__name__).warning("%s sin sub-consultas válidas: %s", eid, exc)
            failed.append(eid)
            continue
        n_pdf = sum(1 for c in record.candidates if not c.from_abstract)
        scores = [c.score for c in record.candidates]
        typer.echo(
            f"{eid}: {len(record.queries)} sub-consultas, {len(record.candidates)} chunks candidatos "
            f"({n_pdf} de PDF) de {len({c.chunk.paper_id for c in record.candidates})}/{len(record.paper_ids)} papers, "
            f"score {min(scores, default=0):.3f}–{max(scores, default=0):.3f} "
            f"→ {retrieval_path(eid, synthesis_dir=settings.synthesis_dir)}"
        )
        for query in record.queries:
            typer.echo(f"    · {query}")
    skipped = len(expected) - len(todo) if expert_id is None else 0
    typer.echo(f"{len(todo) - len(failed)} clústeres procesados, {skipped} ya existentes [{run_id}]")
    if failed:
        typer.echo(f"Sin sub-consultas (reintentar con --expert-id): {', '.join(failed)}", err=True)
        raise typer.Exit(1)


@synthesis_app.command("draft")
def synthesis_draft(
    expert_id: str | None = typer.Option(None, "--expert-id", help="Redactar solo este clúster (p. ej. C8)."),
    run_id: str | None = typer.Option(None, "--run-id", help="Por defecto, `cluster_run_id` de Settings."),
    out_dir: Path | None = typer.Option(
        None, "--out-dir", help="Dónde guardar síntesis y auditoría (por defecto `synthesis_dir`). El retrieval se lee siempre de `synthesis_dir`."
    ),
    force: bool = typer.Option(False, "--force", help="Sin `--expert-id`: redactar también los clústeres que ya tienen síntesis válida."),
) -> None:
    """Claims validadas (1 llamada LLM por clúster) desde `synthesis_dir/_retrieval/` → síntesis C3 + `_draft/`.

    Sin `--expert-id`, omite los clústeres que ya tienen síntesis válida en el directorio de salida
    (reanudar tras un fallo gasta solo las llamadas que faltan), salvo `--force`; con `--expert-id`,
    la regenera siempre.
    """
    _configure_logging()
    settings = Settings()
    run_id = run_id or settings.cluster_run_id
    _check_run_id_matches_vectors(run_id, settings)
    out_dir = out_dir or settings.synthesis_dir

    labels = load_labels(settings.cluster_labels_path, run_id)
    expected = sorted(set(load_corpus_assignment(settings.db_path, run_id).values()), key=lambda e: int(e[1:]))
    if expert_id is not None:
        if expert_id not in expected:
            typer.echo(f"{expert_id} no está en clusters[run_id={run_id}]", err=True)
            raise typer.Exit(1)
        todo = [expert_id]
    else:
        todo = pending_drafts(expected, out_dir=out_dir, force=force)
    missing = [eid for eid in todo if eid not in labels or not retrieval_path(eid, synthesis_dir=settings.synthesis_dir).exists()]
    if missing:
        typer.echo(f"Sin etiqueta o sin retrieval (correr N7): {', '.join(missing)}", err=True)
        raise typer.Exit(1)

    llm_client = make_client("synthesis", settings)
    storage = Storage(settings.db_path)
    failed = []
    for eid in todo:
        try:
            result = run_expert_draft(
                eid,
                llm_client,
                run_id=run_id,
                label=labels[eid],
                excavador_storage=storage,
                synthesis_dir=settings.synthesis_dir,
                out_dir=out_dir,
            )
        except (LLMOutputError, NoValidClaimsError) as exc:
            logging.getLogger(__name__).warning("%s sin síntesis: %s", eid, exc)
            failed.append(eid)
            continue
        s, audit = result
        stances = {st: sum(1 for c in s.key_claims if c.stance == st) for st in ("supports", "contradicts", "mentions")}
        typer.echo(
            f"{eid} [{audit.llm_model}]: {audit.n_kept}/{audit.n_proposed} claims válidas, "
            f"{len(audit.discarded)} descartadas, stance {stances}, "
            f"{len(audit.primary_work_flags)} marcas de obra primaria, summary {len(s.summary.split())} palabras → {out_dir}"
        )
    skipped = len(expected) - len(todo) if expert_id is None else 0
    typer.echo(f"{len(todo) - len(failed)} síntesis redactadas, {skipped} ya existentes [{run_id}]")
    if failed:
        typer.echo(f"Sin síntesis (reintentar con --expert-id): {', '.join(failed)}", err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
