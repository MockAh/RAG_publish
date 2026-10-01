"""Etiquetado LLM de los clústeres (N5).

Una llamada por clúster: el LLM lee los `n` papers más cercanos al centroide
(año · título · abstract truncado) y devuelve un `ClusterLabel`. Las etiquetas
se persisten en `data/cluster_labels.json`, agrupadas por `run_id` (la corrida
original y sus derivadas conviven sin pisarse). Los papers de la stoplist
(`assignments.EXCLUDED_PAPER_IDS`) no entran en ningún prompt.

El centroide es la media de los vectores de los miembros según la tabla
`clusters`, no un k-means recalculado: la partición persistida es la fuente de
verdad (en la convergencia de k-means ambos coinciden).

`one_liner` > 40 palabras se RECHAZA en el schema, no se registra con warning:
el campo pasa tal cual a C4, cuyo límite existe para que el mapa completo
quepa en el contexto del Orquestador (criterio 5, N11). Un warning dejaría
persistir en silencio un valor que rompe el contrato. El rechazo cuesta poco:
el cliente LLM lo convierte en `LLMOutputError` (no se reintenta, así que no
gasta llamadas extra), `label_all_clusters` sigue con los demás clústeres (y guarda tras cada uno,
así que un 429 de cuota diaria no pierde lo ya etiquetado), y
`cluster label --expert-id Cn` reintenta solo el que falló.

Cada llamada lleva `context={"task": "label", "run_id", "expert_id"}` a `llm_calls`, y
`skip_existing=True` no vuelve a llamar por los clústeres ya guardados: una corrida
cortada por un 503 se reanuda gastando solo las llamadas que faltan (cuota de 20/día, A10).
"""

from __future__ import annotations

import html
import json
import logging
import re
from pathlib import Path

import numpy as np
from pydantic import BaseModel, field_validator

from excavador.models import PaperRecord
from expertos.assignments import load_corpus_assignment
from expertos.inspection import PaperLookup, closest_to_centroid
from expertos.llm import LLMClient, LLMOutputError
from expertos.models import check_one_liner

logger = logging.getLogger(__name__)

ABSTRACT_MAX_CHARS = 400

_TAG_RE = re.compile(r"<[^>]+>")


class ClusterLabel(BaseModel):
    """Salida del LLM para un clúster; `one_liner` y `keywords` alimentan C4."""

    topic_label: str  # 3-8 palabras, nombre del tema
    one_liner: str  # ≤ 40 palabras (requisito de C4)
    keywords: list[str]  # 4-8 términos (campo de C4)
    coherent: bool  # False si los papers no comparten tema reconocible
    note: str | None  # por qué no es coherente, o matiz relevante

    _one_liner_fits_c4 = field_validator("one_liner")(check_one_liner)


def _clean(text: str) -> str:
    """Deshace entidades HTML (deuda B2), quita las etiquetas que destapan y colapsa espacios."""
    return " ".join(_TAG_RE.sub(" ", html.unescape(text)).split())


def _truncate(text: str, max_chars: int = ABSTRACT_MAX_CHARS) -> str:
    """Corta en el último espacio antes de `max_chars` y marca el corte con «…»."""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    if " " in cut:
        cut = cut[: cut.rindex(" ")]
    return cut.rstrip(" ,;:.") + "…"


def select_representatives(
    expert_id: str,
    run_id: str,
    n: int = 10,
    *,
    vectors: dict[str, np.ndarray],
    db_path: Path,
    excavador_storage: PaperLookup,
) -> list[PaperRecord]:
    """Los `n` papers de `expert_id` más cercanos al centroide de su clúster en `run_id`
    (todos si el clúster tiene ≤ `n`), del más cercano al más lejano."""
    member_ids = sorted(
        paper_id for paper_id, eid in load_corpus_assignment(db_path, run_id).items() if eid == expert_id
    )
    if not member_ids:
        raise ValueError(f"{expert_id} no tiene papers en clusters[run_id={run_id}]")
    missing = [paper_id for paper_id in member_ids if paper_id not in vectors]
    if missing:
        raise ValueError(f"{len(missing)} papers de {expert_id} sin vector (¿vectores regenerados?): {missing[:3]}")

    X = np.stack([vectors[paper_id] for paper_id in member_ids])
    papers = []
    for index in closest_to_centroid(X, X.mean(axis=0), n):
        paper_id = member_ids[index]
        paper = excavador_storage.get_paper(paper_id)
        if paper is None:
            raise ValueError(f"{paper_id} no está en excavador.db")
        papers.append(paper)
    return papers


def build_label_prompt(papers: list[PaperRecord], n_clusters: int = 9) -> tuple[str, str]:
    """(system, user) para etiquetar un clúster a partir de sus papers representativos."""
    n_others = n_clusters - 1
    system = f"""Eres un bibliotecario académico que pone nombre a un grupo de papers.

Todo el corpus (dividido en {n_clusters} grupos temáticos) trata sobre Bolívar Echeverría,
así que «Bolívar Echeverría» NO es una etiqueta útil. La etiqueta debe distinguir este
grupo de los otros {n_others}: nombra el ángulo, el concepto o la línea de recepción
concreta que estos papers tratan.

Reglas:
- Nombra lo que los papers REALMENTE comparten según sus títulos y resúmenes, no lo que
  «deberían» compartir ni lo que sabes de la obra de Echeverría.
- topic_label nombra SIEMPRE el tema dominante del grupo, aunque el grupo sea disperso.
  La dispersión no va en la etiqueta: si el conjunto es heterogéneo, pon coherent=false
  y explica en note qué subgrupos o qué dispersión ves. No inventes un tema paraguas
  vago que tape la heterogeneidad.
- No uses «Misceláneo» salvo que ningún tema reúna siquiera a una minoría clara de los
  papers (el grupo residual del corpus).
- Si hay un rasgo no temático que une al grupo (p. ej. todas las piezas vienen del mismo
  volumen o son reseñas), dilo en note.
- topic_label: 3 a 8 palabras.
- one_liner: una oración de 40 palabras como máximo. Lo lee un Orquestador que decide
  si enruta a este grupo una pregunta de investigación: di qué preguntas puede responder
  este grupo, con términos concretos.
- keywords: entre 4 y 8 términos específicos del grupo (no «Bolívar Echeverría»).
- Responde en español."""

    lines = [f"Papers representativos del grupo ({len(papers)}, del más central al menos central):", ""]
    for i, paper in enumerate(papers, start=1):
        year = paper.year if paper.year is not None else "s.f."
        entry = f"{i}. {year} · {_clean(paper.title)}"
        abstract = _clean(paper.abstract or "")
        if abstract:
            entry += f" · {_truncate(abstract)}"
        lines.append(entry)
    return system, "\n".join(lines)


def label_cluster(
    expert_id: str,
    llm_client: LLMClient,
    *,
    run_id: str,
    vectors: dict[str, np.ndarray],
    db_path: Path,
    excavador_storage: PaperLookup,
    n: int = 10,
    n_clusters: int | None = None,
) -> ClusterLabel:
    """Una llamada LLM para etiquetar `expert_id`."""
    if n_clusters is None:
        n_clusters = len(set(load_corpus_assignment(db_path, run_id).values()))
    papers = select_representatives(
        expert_id, run_id, n, vectors=vectors, db_path=db_path, excavador_storage=excavador_storage
    )
    system, user = build_label_prompt(papers, n_clusters=n_clusters)
    context = {"task": "label", "run_id": run_id, "expert_id": expert_id}
    return llm_client.complete_json(system, user, ClusterLabel, context=context)


def label_all_clusters(
    llm_client: LLMClient,
    *,
    run_id: str,
    vectors: dict[str, np.ndarray],
    db_path: Path,
    excavador_storage: PaperLookup,
    n: int = 10,
    labels_path: Path | None = None,
    skip_existing: bool = False,
) -> dict[str, ClusterLabel]:
    """Etiqueta todos los clústeres de `run_id`, una llamada cada uno.

    Con `labels_path`, cada etiqueta se guarda en cuanto llega (fundida con las ya
    guardadas para `run_id`), así que un error a mitad de corrida no pierde las
    anteriores. Un `LLMOutputError` (JSON inválido o fuera del schema, p. ej.
    one_liner largo) se registra y ese clúster queda fuera del resultado, para
    reintentarlo con `--expert-id`; cualquier otro error (cuota, red) se propaga.

    Con `skip_existing=True` (exige `labels_path`), los clústeres que ya tienen
    etiqueta en `labels_path` para `run_id` no se llaman. Devuelve solo las
    etiquetas nuevas de esta corrida; el conjunto completo está en `labels_path`.
    """
    if skip_existing and labels_path is None:
        raise ValueError("skip_existing=True exige labels_path")
    expert_ids = sorted(set(load_corpus_assignment(db_path, run_id).values()), key=lambda e: int(e[1:]))
    if not expert_ids:
        raise ValueError(f"clusters[run_id={run_id}] está vacío")
    existing = set(load_labels(labels_path, run_id)) if skip_existing else set()
    labels = {}
    for expert_id in expert_ids:
        if expert_id in existing:
            logger.info("%s ya etiquetado en %s; se omite", expert_id, labels_path)
            continue
        try:
            labels[expert_id] = label_cluster(
                expert_id,
                llm_client,
                run_id=run_id,
                vectors=vectors,
                db_path=db_path,
                excavador_storage=excavador_storage,
                n=n,
                n_clusters=len(expert_ids),
            )
        except LLMOutputError as exc:
            logger.warning("%s sin etiqueta (reintentar con --expert-id %s): %s", expert_id, expert_id, exc)
            continue
        if labels_path is not None:
            update_labels(labels_path, run_id, {expert_id: labels[expert_id]})
    return labels


def _read_runs(path: Path) -> dict:
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_labels(path: Path, run_id: str, labels: dict[str, ClusterLabel]) -> None:
    """Reemplaza las etiquetas de `run_id` en `{run_id: {expert_id: ClusterLabel}}`,
    sin tocar las de otras corridas."""
    runs = _read_runs(path)
    runs[run_id] = {expert_id: label.model_dump(mode="json") for expert_id, label in sorted(labels.items())}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(runs.items())), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_labels(path: Path, run_id: str) -> dict[str, ClusterLabel]:
    """Inverso de `save_labels`; vacío si el archivo no existe o no tiene `run_id`."""
    runs = _read_runs(path)
    return {expert_id: ClusterLabel.model_validate(data) for expert_id, data in runs.get(run_id, {}).items()}


def update_labels(path: Path, run_id: str, labels: dict[str, ClusterLabel]) -> None:
    """Funde `labels` con las ya guardadas para `run_id` (las nuevas ganan)."""
    save_labels(path, run_id, load_labels(path, run_id) | labels)
