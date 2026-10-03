"""Tests para expertos.synthesis (N7): sub-consultas, retrieval por partición y archivo intermedio."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from biblioteca.models import Chunk, ScoredChunk
from expertos.assignments import EXCLUDED_PAPER_IDS, save_assignment
from expertos.labeling import ClusterLabel
from expertos.llm import LLMOutputError
from expertos.synthesis import (
    CandidateChunk,
    RetrievalRecord,
    SubQueries,
    build_subqueries_prompt,
    collect_candidate_chunks,
    generate_subqueries,
    load_retrieval,
    retrieval_path,
    retrieve_for_expert,
    save_retrieval,
    subqueries_schema,
)
from tests.expertos.test_expertos_labeling import _paper

RUN_ID = "kmeans-k9-seed42-0123abcd"
[EXCLUDED] = EXCLUDED_PAPER_IDS

_LABEL = ClusterLabel(
    topic_label="Ethos barroco y mestizaje cultural",
    one_liner="Papers sobre el ethos barroco como estrategia de vida en la modernidad latinoamericana.",
    keywords=["ethos barroco", "mestizaje", "modernidad", "América Latina"],
    coherent=True,
    note=None,
)


def _queries(n: int) -> list[str]:
    return [f"ethos barroco y ángulo número {i}" for i in range(n)]


class DummyLLM:
    """Imita al cliente real: valida el JSON contra el schema y envuelve el fallo en `LLMOutputError`."""

    def __init__(self, queries: list[str]) -> None:
        self.calls: list[tuple[str, str]] = []
        self.contexts: list[dict | None] = []
        self._raw = json.dumps({"queries": queries}, ensure_ascii=False)

    def complete_json(self, system: str, user: str, schema, *, context=None):
        self.calls.append((system, user))
        self.contexts.append(context)
        try:
            return schema.model_validate_json(self._raw)
        except ValidationError as exc:
            raise LLMOutputError(str(exc)) from exc


def _chunk(paper_id: str, seq: int, text: str = "Un pasaje sobre el ethos barroco.") -> Chunk:
    return Chunk(
        chunk_id=Chunk.build_id(paper_id, "body", seq),
        paper_id=paper_id,
        section="body",
        text=text,
        char_start=0,
        char_end=len(text),
        embedding_model="intfloat/multilingual-e5-large",
    )


class DummyStore:
    """Devuelve, por consulta, los chunks dados; registra cada llamada y respeta el filtro como Chroma."""

    def __init__(self, results: dict[str, list[ScoredChunk]] | None = None) -> None:
        self.calls: list[dict] = []
        self._results = results or {}

    def retrieve(self, query, top_k=8, filter_paper_ids=None):
        self.calls.append({"query": query, "top_k": top_k, "filter_paper_ids": filter_paper_ids})
        hits = self._results.get(query, [])
        return [sc for sc in hits if filter_paper_ids is None or sc.chunk.paper_id in filter_paper_ids][:top_k]


def _db(tmp_path: Path) -> Path:
    """C0 = 3 papers + el de la stoplist; C1 = 2 papers."""
    db_path = tmp_path / "excavador.db"
    assignment = {"doi:a": "C0", "doi:b": "C0", "doi:c": "C0", EXCLUDED: "C0", "doi:x": "C1", "doi:y": "C1"}
    save_assignment(db_path, RUN_ID, assignment)
    return db_path


# --- SubQueries / generate_subqueries ----------------------------------------------


def test_generate_subqueries_makes_exactly_one_call() -> None:
    llm = DummyLLM(_queries(10))

    queries = generate_subqueries("C3", _LABEL, [_paper("doi:a"), _paper("doi:b")], llm, run_id=RUN_ID)

    assert queries == _queries(10)
    assert len(llm.calls) == 1
    assert llm.contexts == [{"task": "synthesis.subqueries", "expert_id": "C3", "run_id": RUN_ID}]


@pytest.mark.parametrize("n", [7, 13])
def test_out_of_range_count_is_rejected(n: int) -> None:
    llm = DummyLLM(_queries(n))

    with pytest.raises(LLMOutputError, match="entre 8 y 12"):
        generate_subqueries("C3", _LABEL, [_paper("doi:a")], llm)
    assert len(llm.calls) == 1  # sin reintentos


@pytest.mark.parametrize("n", [8, 12])
def test_bounds_are_inclusive(n: int) -> None:
    assert len(SubQueries(queries=_queries(n)).queries) == n


def test_exact_duplicates_are_rejected_even_with_surrounding_spaces() -> None:
    queries = _queries(9) + ["  ethos barroco y ángulo número 0 "]

    with pytest.raises(ValidationError, match="duplicadas"):
        SubQueries(queries=queries)


def test_empty_query_is_rejected() -> None:
    with pytest.raises(ValidationError, match="vacías"):
        SubQueries(queries=_queries(9) + ["   "])


def test_custom_bounds_derive_a_schema_without_touching_the_default() -> None:
    llm = DummyLLM(_queries(4))

    assert generate_subqueries("C3", _LABEL, [_paper("doi:a")], llm, n_min=3, n_max=5) == _queries(4)
    assert (SubQueries.n_min, SubQueries.n_max) == (8, 12)
    with pytest.raises(ValueError):
        subqueries_schema(6, 5)


def test_prompt_carries_label_keywords_and_titles_and_forbids_asking_for_critiques() -> None:
    papers = [_paper("doi:a", title="La modernidad de lo barroco"), _paper("doi:b", title="Crítica &amp; ethos")]

    system, user = build_subqueries_prompt(_LABEL, papers, 8, 12)

    assert "entre 8 y 12" in system
    assert "No pidas críticas" in system  # L2
    assert "preguntas retóricas" in system
    assert _LABEL.topic_label in user and _LABEL.one_liner in user
    assert "ethos barroco, mestizaje, modernidad, América Latina" in user
    assert "1. La modernidad de lo barroco" in user
    assert "2. Crítica & ethos" in user  # entidades HTML deshechas


# --- retrieve_for_expert ---------------------------------------------------------


def test_retrieve_filters_by_the_cluster_partition_without_the_stoplist(tmp_path: Path) -> None:
    db_path = _db(tmp_path)
    store = DummyStore()

    retrieved = retrieve_for_expert("C0", RUN_ID, ["q1", "q2"], store, top_k=5, db_path=db_path)

    assert list(retrieved) == ["q1", "q2"]
    assert [call["query"] for call in store.calls] == ["q1", "q2"]
    for call in store.calls:
        assert call["filter_paper_ids"] == ["doi:a", "doi:b", "doi:c"]
        assert EXCLUDED not in call["filter_paper_ids"]
        assert call["top_k"] == 5


def test_retrieve_with_empty_partition_raises_instead_of_searching_the_whole_corpus(tmp_path: Path) -> None:
    store = DummyStore()

    with pytest.raises(ValueError, match="no tiene papers"):
        retrieve_for_expert("C7", RUN_ID, ["q1"], store, db_path=_db(tmp_path))
    assert store.calls == []


def test_retrieve_rejects_chunks_outside_the_partition(tmp_path: Path) -> None:
    class LeakyStore(DummyStore):
        def retrieve(self, query, top_k=8, filter_paper_ids=None):
            return [ScoredChunk(chunk=_chunk("doi:x", 0), score=0.88, from_abstract=False)]

    with pytest.raises(RuntimeError, match="fuera de la partición"):
        retrieve_for_expert("C0", RUN_ID, ["q1"], LeakyStore(), db_path=_db(tmp_path))


# --- collect_candidate_chunks ----------------------------------------------------


def test_chunk_from_two_queries_appears_once_with_best_score_and_both_queries() -> None:
    shared, only_q1, only_q2 = _chunk("doi:a", 0), _chunk("doi:b", 0), _chunk("doi:c", 0)
    retrieved = {
        "q1": [
            ScoredChunk(chunk=shared, score=0.84, from_abstract=False),
            ScoredChunk(chunk=only_q1, score=0.86, from_abstract=True),
        ],
        "q2": [
            ScoredChunk(chunk=shared, score=0.89, from_abstract=False),
            ScoredChunk(chunk=only_q2, score=0.83, from_abstract=False),
        ],
    }

    candidates = collect_candidate_chunks(retrieved)

    assert [c.chunk.chunk_id for c in candidates] == [shared.chunk_id, only_q1.chunk_id, only_q2.chunk_id]
    first = candidates[0]
    assert first.score == 0.89
    assert first.queries == ["q1", "q2"]
    assert candidates[1].from_abstract is True and candidates[1].queries == ["q1"]
    assert all(isinstance(c, ScoredChunk) for c in candidates)


def test_collect_does_not_filter_low_scores() -> None:
    """L1: ningún umbral; un 0.10 llega a N8 igual que un 0.90."""
    retrieved = {"q1": [ScoredChunk(chunk=_chunk("doi:a", 0), score=0.10, from_abstract=False)]}

    assert [c.score for c in collect_candidate_chunks(retrieved)] == [0.10]


# --- archivo de retrieval --------------------------------------------------------


def _record(expert_id: str = "C0") -> RetrievalRecord:
    text = "El ethos barroco, según Echeverría, es una estrategia de resistencia; ñandú, acción, «cita»."
    return RetrievalRecord(
        expert_id=expert_id,
        run_id=RUN_ID,
        created_at=datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc),
        llm_provider="deepseek",
        llm_model="deepseek-flash",
        topic_label="Ethos barroco y mestizaje",
        paper_ids=["doi:a", "doi:b"],
        top_k=8,
        queries=["ethos barroco y resistencia", "mestizaje cultural en la Colonia"],
        candidates=[
            CandidateChunk(
                chunk=_chunk("doi:a", 3, text),
                score=0.87,
                from_abstract=False,
                queries=["ethos barroco y resistencia", "mestizaje cultural en la Colonia"],
            ),
            CandidateChunk(
                chunk=_chunk("doi:b", 0), score=0.84, from_abstract=True, queries=["mestizaje cultural en la Colonia"]
            ),
        ],
    )


def test_retrieval_file_round_trip_with_accents(tmp_path: Path) -> None:
    record = _record()

    path = save_retrieval(record, synthesis_dir=tmp_path / "synthesis")

    assert path == tmp_path / "synthesis" / "_retrieval" / "C0.json"
    assert load_retrieval("C0", synthesis_dir=tmp_path / "synthesis") == record
    raw = path.read_text(encoding="utf-8")
    assert "ñandú" in raw and "«cita»" in raw  # UTF-8 legible, no escapes \\u
    assert json.loads(raw)["candidates"][1]["from_abstract"] is True


def test_load_retrieval_missing_returns_none(tmp_path: Path) -> None:
    assert load_retrieval("C4", synthesis_dir=tmp_path) is None


def test_retrieval_path_rejects_path_like_expert_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        retrieval_path("../C0", synthesis_dir=tmp_path)


def test_retrieval_files_are_not_read_as_syntheses(tmp_path: Path) -> None:
    """`load_all_syntheses` lee `synthesis_dir/*.json`; el subdirectorio `_retrieval/` no le afecta."""
    from expertos.persistence import load_all_syntheses

    save_retrieval(_record(), synthesis_dir=tmp_path)

    assert load_all_syntheses(synthesis_dir=tmp_path) == {}


# --- corrida real -----------------------------------------------------------------


@pytest.mark.slow
def test_real_retrieval_for_one_cluster() -> None:
    """Extremo a extremo desde la raíz del repo: un clúster, 1 llamada al LLM de síntesis.

    Escribe en `data/synthesis_slowtest/_retrieval/` (fuera de git), no en `synthesis_dir`,
    para no pisar el material de producción.
    """
    from biblioteca.store import ChunkStore
    from excavador.storage import Storage
    from expertos.config import Settings
    from expertos.labeling import load_labels
    from expertos.llm import make_client
    from expertos.synthesis import partition_paper_ids, run_expert_retrieval
    from expertos.vectors import load_vectors

    try:
        settings = Settings()
    except ValidationError:
        pytest.skip("Configuración de Expertos incompleta")

    expert_id = "C3"
    run_id = settings.cluster_run_id
    synthesis_dir = settings.synthesis_dir.with_name("synthesis_slowtest")
    record = run_expert_retrieval(
        expert_id,
        make_client("synthesis", settings),
        ChunkStore(settings.chroma_dir),
        run_id=run_id,
        label=load_labels(settings.cluster_labels_path, run_id)[expert_id],
        vectors=load_vectors(settings.expert_vectors_path),
        db_path=settings.db_path,
        excavador_storage=Storage(settings.db_path),
        synthesis_dir=synthesis_dir,
    )

    assert 8 <= len(record.queries) <= 12
    assert record.candidates
    partition = set(partition_paper_ids(expert_id, run_id, settings.db_path))
    assert {c.chunk.paper_id for c in record.candidates} <= partition
    assert len({c.chunk.chunk_id for c in record.candidates}) == len(record.candidates)
    assert load_retrieval(expert_id, synthesis_dir=synthesis_dir) == record
