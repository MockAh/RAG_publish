"""Tests para expertos.labeling (N5)."""

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from excavador.models import PaperRecord
from expertos.assignments import save_assignment
from expertos.labeling import (
    ClusterLabel,
    build_label_prompt,
    label_all_clusters,
    load_labels,
    save_labels,
    select_representatives,
    update_labels,
)
from expertos.llm import LLMOutputError

RUN_ID = "kmeans-k9-seed42-0123abcd"
N_CLUSTERS = 9

_VALID_LABEL = {
    "topic_label": "Ethos barroco y mestizaje cultural",
    "one_liner": "Papers sobre el ethos barroco como estrategia de vida en la modernidad latinoamericana.",
    "keywords": ["ethos barroco", "mestizaje", "modernidad", "América Latina"],
    "coherent": True,
    "note": None,
}


def _paper(paper_id: str, title: str | None = None, abstract: str = "Un abstract.") -> PaperRecord:
    return PaperRecord(
        paper_id=paper_id,
        doi=None,
        title=title if title is not None else f"Título {paper_id}",
        authors=["Autora"],
        year=2020,
        venue=None,
        abstract=abstract,
        source_api="openalex",
        work_type="article",
        pdf_path=None,
        relevance_score=0.9,
        references_ids=[],
        ingested_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


class LabelingDummyStorage:
    def __init__(self, papers: list[PaperRecord]) -> None:
        self._papers = {paper.paper_id: paper for paper in papers}

    def get_paper(self, paper_id: str) -> PaperRecord | None:
        return self._papers.get(paper_id)


class DummyLLM:
    """Imita a `GeminiClient`: valida el JSON contra el schema y envuelve el fallo en `LLMOutputError`."""

    def __init__(self, responses: dict[str, dict] | None = None, fail_on_call: int | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.contexts: list[dict[str, str] | None] = []
        self._responses = responses or {}
        self._fail_on_call = fail_on_call

    def complete_json(self, system: str, user: str, schema, *, context=None):
        self.calls.append((system, user))
        self.contexts.append(context)
        if len(self.calls) == self._fail_on_call:
            raise RuntimeError("429 RESOURCE_EXHAUSTED (cuota diaria)")
        # La respuesta se elige por el primer paper listado (`N. año · Título pid · …`).
        first_paper = user.splitlines()[2].split(" · ")[1]
        raw = json.dumps(self._responses.get(first_paper, _VALID_LABEL))
        try:
            return schema.model_validate_json(raw)
        except ValidationError as exc:
            raise LLMOutputError(str(exc)) from exc


def _corpus(tmp_path: Path, sizes: list[int]) -> dict:
    """Un clúster por tamaño de `sizes`, con vectores unitarios agrupados alrededor de ejes distintos."""
    rng = np.random.default_rng(0)
    vectors, assignment, papers = {}, {}, []
    for cluster, size in enumerate(sizes):
        for i in range(size):
            paper_id = f"doi:c{cluster}-{i:02d}"
            v = np.zeros(16)
            v[cluster] = 10.0
            v += rng.normal(size=16)
            vectors[paper_id] = v / np.linalg.norm(v)
            assignment[paper_id] = f"C{cluster}"
            papers.append(_paper(paper_id))
    db_path = tmp_path / "excavador.db"
    save_assignment(db_path, RUN_ID, assignment)
    return dict(run_id=RUN_ID, vectors=vectors, db_path=db_path, excavador_storage=LabelingDummyStorage(papers))


# --- select_representatives -------------------------------------------------------


def test_selects_n_closest_to_centroid_in_order(tmp_path: Path) -> None:
    # Un clúster en el círculo unidad, simétrico respecto a 0°: el centroide cae sobre el eje de 0°.
    angles = [80, -40, 10, 0, -80, 40, -10]
    vectors = {f"deg:{a}": np.array([np.cos(np.radians(a)), np.sin(np.radians(a))]) for a in angles}
    db_path = tmp_path / "excavador.db"
    save_assignment(db_path, RUN_ID, {paper_id: "C0" for paper_id in vectors} | {"otro": "C1"})
    storage = LabelingDummyStorage([_paper(paper_id) for paper_id in vectors])

    papers = select_representatives(
        "C0", RUN_ID, n=5, vectors=vectors | {"otro": np.array([0.0, 1.0])}, db_path=db_path,
        excavador_storage=storage,
    )

    ids = [paper.paper_id for paper in papers]
    assert len(ids) == 5
    assert ids[0] == "deg:0"
    assert set(ids[1:3]) == {"deg:10", "deg:-10"}
    assert set(ids[3:5]) == {"deg:40", "deg:-40"}


def test_cluster_smaller_than_n_returns_all_members(tmp_path: Path) -> None:
    context = _corpus(tmp_path, [12, 5])

    papers = select_representatives("C1", RUN_ID, n=10, **{k: context[k] for k in context if k != "run_id"})

    assert sorted(paper.paper_id for paper in papers) == [f"doi:c1-{i:02d}" for i in range(5)]


def test_unknown_expert_id_raises(tmp_path: Path) -> None:
    context = _corpus(tmp_path, [3])
    with pytest.raises(ValueError, match="C7"):
        select_representatives("C7", RUN_ID, **{k: context[k] for k in context if k != "run_id"})


# --- build_label_prompt -----------------------------------------------------------


def test_prompt_lists_every_paper_with_unescaped_title() -> None:
    papers = [_paper(f"doi:{i}") for i in range(9)]
    papers.append(_paper("doi:html", title="La &lt;i&gt;modernidad&lt;/i&gt; de lo barroco"))

    system, user = build_label_prompt(papers)

    for paper in papers[:9]:
        assert paper.title in user
    assert "La modernidad de lo barroco" in user
    assert "&lt;" not in user
    assert "<i>" not in user
    assert "Bolívar Echeverría" in system
    assert "coherent" in system
    assert "tema dominante" in system


def test_prompt_truncates_abstract_and_omits_missing_one() -> None:
    long_abstract = "&lt;p&gt;" + " ".join(["palabra"] * 200) + "&lt;/p&gt;"
    papers = [
        _paper("doi:long", title="Largo", abstract=long_abstract),
        _paper("doi:none", title="Sin resumen", abstract=""),
    ]

    _, user = build_label_prompt(papers)

    long_line, none_line = user.splitlines()[2:4]
    abstract_part = long_line.split(" · ", 2)[2]
    assert abstract_part.endswith("…")
    assert len(abstract_part) <= 401
    assert "<p>" not in long_line
    assert none_line == "2. 2020 · Sin resumen"


# --- label_all_clusters -----------------------------------------------------------


def test_label_all_makes_exactly_one_call_per_cluster(tmp_path: Path) -> None:
    context = _corpus(tmp_path, [12, 10, 9, 8, 7, 6, 5, 4, 3])
    llm = DummyLLM()

    labels = label_all_clusters(llm, **context)

    assert len(llm.calls) == N_CLUSTERS
    assert sorted(labels, key=lambda e: int(e[1:])) == [f"C{i}" for i in range(N_CLUSTERS)]
    assert "otros 8" in llm.calls[0][0]


def test_long_one_liner_is_rejected_by_schema() -> None:
    ClusterLabel.model_validate(_VALID_LABEL | {"one_liner": " ".join(["w"] * 40)})

    with pytest.raises(ValidationError, match="41 palabras"):
        ClusterLabel.model_validate(_VALID_LABEL | {"one_liner": " ".join(["w"] * 41)})


def test_long_one_liner_skips_that_cluster_without_extra_calls(tmp_path: Path) -> None:
    context = _corpus(tmp_path, [4, 4, 4])
    # El primer paper listado de C1 es uno de sus miembros; se le asigna la respuesta inválida.
    first_c1 = select_representatives("C1", RUN_ID, **{k: context[k] for k in context if k != "run_id"})[0]
    llm = DummyLLM({first_c1.title: _VALID_LABEL | {"one_liner": " ".join(["w"] * 41)}})

    labels = label_all_clusters(llm, **context)

    assert len(llm.calls) == 3
    assert set(labels) == {"C0", "C2"}


def test_label_all_saves_after_each_cluster_so_a_quota_error_keeps_earlier_ones(tmp_path: Path) -> None:
    context = _corpus(tmp_path, [4, 4, 4])
    labels_path = tmp_path / "cluster_labels.json"

    with pytest.raises(RuntimeError, match="429"):
        label_all_clusters(DummyLLM(fail_on_call=3), **context, labels_path=labels_path)

    assert set(load_labels(labels_path, RUN_ID)) == {"C0", "C1"}


def test_each_call_carries_its_expert_id_as_context(tmp_path: Path) -> None:
    context = _corpus(tmp_path, [4, 4, 4])
    llm = DummyLLM()

    label_all_clusters(llm, **context)

    assert llm.contexts == [{"task": "label", "run_id": RUN_ID, "expert_id": f"C{i}"} for i in range(3)]


def test_skip_existing_resumes_a_cut_run_calling_only_the_missing_clusters(tmp_path: Path) -> None:
    context = _corpus(tmp_path, [4, 4, 4, 4])
    labels_path = tmp_path / "cluster_labels.json"
    with pytest.raises(RuntimeError, match="429"):
        label_all_clusters(DummyLLM(fail_on_call=3), **context, labels_path=labels_path, skip_existing=True)
    assert set(load_labels(labels_path, RUN_ID)) == {"C0", "C1"}

    llm = DummyLLM()
    new_labels = label_all_clusters(llm, **context, labels_path=labels_path, skip_existing=True)

    assert [ctx["expert_id"] for ctx in llm.contexts] == ["C2", "C3"]
    assert set(new_labels) == {"C2", "C3"}
    assert set(load_labels(labels_path, RUN_ID)) == {"C0", "C1", "C2", "C3"}


def test_skip_existing_ignores_labels_of_other_runs(tmp_path: Path) -> None:
    context = _corpus(tmp_path, [4, 4])
    labels_path = tmp_path / "cluster_labels.json"
    save_labels(labels_path, "otra-corrida", {"C0": ClusterLabel.model_validate(_VALID_LABEL)})
    llm = DummyLLM()

    label_all_clusters(llm, **context, labels_path=labels_path, skip_existing=True)

    assert len(llm.calls) == 2


def test_skip_existing_without_labels_path_raises(tmp_path: Path) -> None:
    context = _corpus(tmp_path, [4])

    with pytest.raises(ValueError, match="labels_path"):
        label_all_clusters(DummyLLM(), **context, skip_existing=True)


def test_excluded_paper_never_reaches_the_prompt(tmp_path: Path) -> None:
    context = _corpus(tmp_path, [4, 4])
    excluded = "doi:10.1002/ajpa.22921"
    save_assignment(context["db_path"], RUN_ID, {pid: f"C{pid[5]}" for pid in context["vectors"]} | {excluded: "C1"})
    context["vectors"][excluded] = context["vectors"]["doi:c1-00"]
    llm = DummyLLM()

    papers = select_representatives("C1", RUN_ID, **{k: context[k] for k in context if k != "run_id"})
    label_all_clusters(llm, **context)

    assert excluded not in [paper.paper_id for paper in papers]
    assert len(papers) == 4
    assert all(excluded not in user for _, user in llm.calls)


# --- persistencia -----------------------------------------------------------------


def test_labels_json_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "cluster_labels.json"
    labels = {
        "C0": ClusterLabel.model_validate(_VALID_LABEL),
        "C1": ClusterLabel.model_validate(
            _VALID_LABEL | {"topic_label": "Misceláneo: reseñas y homenajes", "coherent": False, "note": "Mezcla."}
        ),
    }

    save_labels(path, RUN_ID, labels)

    assert load_labels(path, RUN_ID) == labels
    assert list(json.loads(path.read_text(encoding="utf-8"))) == [RUN_ID]
    assert load_labels(path, "otra-corrida") == {}
    assert load_labels(tmp_path / "no-existe.json", RUN_ID) == {}


def test_derived_run_labels_do_not_overwrite_the_original_run(tmp_path: Path) -> None:
    path = tmp_path / "cluster_labels.json"
    original = {f"C{i}": ClusterLabel.model_validate(_VALID_LABEL) for i in range(9)}
    save_labels(path, RUN_ID, original)
    merged_c0 = ClusterLabel.model_validate(_VALID_LABEL | {"topic_label": "Crítica de la modernidad fusionada"})

    update_labels(path, f"{RUN_ID}+merge-C8-C0", {"C0": merged_c0})
    update_labels(path, RUN_ID, {"C1": merged_c0})

    assert load_labels(path, f"{RUN_ID}+merge-C8-C0") == {"C0": merged_c0}
    assert load_labels(path, RUN_ID) == original | {"C1": merged_c0}


# --- corrida real -----------------------------------------------------------------


@pytest.mark.slow
def test_real_labeling_of_9_clusters() -> None:
    """Corrida real (desde la raíz del repo) contra `model_label`: 9 etiquetas válidas.

    Reanudable: las etiquetas se guardan en `data/cluster_labels_slowtest.json` (fuera de
    git, junto a `cluster_labels_path`) en cuanto llegan, y `skip_existing` no vuelve a
    llamar por las ya guardadas. Tras un 503, relanzar cuesta solo los clústeres que
    faltan; cuáles fallaron está en `llm_calls.context`. Borrar el archivo para empezar de cero.
    """
    from excavador.storage import Storage
    from expertos.config import Settings
    from expertos.llm import make_client
    from expertos.vectors import load_vectors

    try:
        settings = Settings()
    except ValidationError:
        pytest.skip("Configuración de Expertos incompleta (falta EXPERTOS_GEMINI_API_KEY o modelos)")

    labels_path = settings.cluster_labels_path.with_name("cluster_labels_slowtest.json")

    label_all_clusters(
        make_client("label", settings),
        run_id=settings.cluster_run_id,
        vectors=load_vectors(settings.expert_vectors_path),
        db_path=settings.db_path,
        excavador_storage=Storage(settings.db_path),
        labels_path=labels_path,
        skip_existing=True,
    )

    # Las 9, vengan de esta corrida o de una anterior cortada.
    labels = load_labels(labels_path, settings.cluster_run_id)
    assert sorted(labels, key=lambda e: int(e[1:])) == [f"C{i}" for i in range(9)]
    for label in labels.values():
        assert "bolívar echeverría" not in label.topic_label.lower()
        assert label.coherent or label.note
