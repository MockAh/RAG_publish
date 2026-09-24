"""Tests para expertos.vectors (N2)."""

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from biblioteca.config import Settings as BibliotecaSettings
from biblioteca.embedder import Embedder
from biblioteca.models import Chunk, ScoredChunk
from excavador.models import PaperRecord
from expertos.vectors import (
    build_representative_vectors,
    get_indexed_paper_ids,
    load_vectors,
    save_vectors,
)

DIM = 4


def _paper(paper_id: str, abstract: str = "Un abstract.") -> PaperRecord:
    return PaperRecord(
        paper_id=paper_id,
        doi=None,
        title=f"Título {paper_id}",
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


class FakeEncoder:
    """Sustituye al `SentenceTransformer`: registra los textos que recibe (ya con prefijo)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def encode(self, texts: str | list[str]) -> list[list[float]] | list[float]:
        if isinstance(texts, str):
            self.calls.append(texts)
            return [1.0] * DIM
        self.calls.extend(texts)
        return [[float(len(text)), 1.0, 0.0, 0.0] for text in texts]


class DummyStorage:
    def __init__(self, papers: list[PaperRecord]) -> None:
        self._papers = {paper.paper_id: paper for paper in papers}

    def get_paper(self, paper_id: str) -> PaperRecord | None:
        return self._papers.get(paper_id)

    def all_papers(self) -> list[PaperRecord]:
        return list(self._papers.values())


class DummyChunkStore:
    """Store con chunks en memoria; `retrieve` filtra por paper sin tocar el embedder."""

    def __init__(self, chunk_texts: dict[str, list[str]]) -> None:
        self._chunk_texts = chunk_texts
        self.retrieve_calls: list[list[str] | None] = []

    def has_paper(self, paper_id: str) -> bool:
        return bool(self._chunk_texts.get(paper_id))

    def count(self) -> int:
        return sum(len(texts) for texts in self._chunk_texts.values())

    def retrieve(self, query, top_k=8, filter_paper_ids=None, filter_sections=None, embedder=None):
        self.retrieve_calls.append(filter_paper_ids)
        return [
            ScoredChunk(
                chunk=Chunk(
                    chunk_id=f"{paper_id}#{i}",
                    paper_id=paper_id,
                    section="body",
                    text=text,
                    char_start=0,
                    char_end=len(text),
                    embedding_model="dummy",
                ),
                score=0.9,
                from_abstract=False,
            )
            for paper_id in filter_paper_ids or []
            for i, text in enumerate(self._chunk_texts.get(paper_id, []))
        ][:top_k]


@pytest.fixture
def encoder() -> FakeEncoder:
    return FakeEncoder()


@pytest.fixture
def embedder(encoder: FakeEncoder) -> Embedder:
    return Embedder("dummy", encoder=encoder)


def test_papers_with_abstract_use_title_and_abstract(encoder: FakeEncoder, embedder: Embedder) -> None:
    """Con abstract, ningún paper cae al camino de media de chunks."""
    papers = [_paper("doi:10.1/a"), _paper("doi:10.1/b")]
    store = DummyChunkStore({"doi:10.1/a": ["x"], "doi:10.1/b": ["y"]})

    vectors = build_representative_vectors(
        ["doi:10.1/a", "doi:10.1/b"], DummyStorage(papers), store, embedder
    )

    assert list(vectors) == ["doi:10.1/a", "doi:10.1/b"]
    assert store.retrieve_calls == []
    assert encoder.calls == [
        "passage: Título doi:10.1/a. Un abstract.",
        "passage: Título doi:10.1/b. Un abstract.",
    ]


def test_paper_without_abstract_uses_mean_of_chunks(encoder: FakeEncoder, embedder: Embedder) -> None:
    """Sin abstract, el vector es la media (renormalizada) de sus chunks y no se lanza excepción."""
    papers = [_paper("doi:10.1/a"), _paper("doi:10.1/sin", abstract="  ")]
    store = DummyChunkStore({"doi:10.1/a": ["x"], "doi:10.1/sin": ["uno", "dos tres"]})

    vectors = build_representative_vectors(
        ["doi:10.1/a", "doi:10.1/sin"], DummyStorage(papers), store, embedder
    )

    assert store.retrieve_calls == [["doi:10.1/sin"]]
    expected = np.mean([[len("passage: uno"), 1, 0, 0], [len("passage: dos tres"), 1, 0, 0]], axis=0)
    expected = expected / np.linalg.norm(expected)
    np.testing.assert_allclose(vectors["doi:10.1/sin"], expected, rtol=1e-6)
    assert vectors["doi:10.1/sin"].shape == (DIM,)


def test_every_vector_uses_passage_prefix(encoder: FakeEncoder, embedder: Embedder) -> None:
    """Todo texto que llega al encoder, en ambos caminos, lleva "passage: " (nunca "query: ")."""
    papers = [_paper("doi:10.1/a"), _paper("doi:10.1/sin", abstract="")]
    store = DummyChunkStore({"doi:10.1/a": ["x"], "doi:10.1/sin": ["uno", "dos"]})

    build_representative_vectors(["doi:10.1/a", "doi:10.1/sin"], DummyStorage(papers), store, embedder)

    assert len(encoder.calls) == 3  # 1 abstract + 2 chunks
    assert all(text.startswith("passage: ") for text in encoder.calls)
    assert not any(text.startswith("query: ") for text in encoder.calls)


def test_save_load_round_trip(tmp_path: Path) -> None:
    """`load_vectors(save_vectors(v))` devuelve los mismos ids, valores y dimensión."""
    rng = np.random.default_rng(0)
    vectors = {
        "doi:10.1234/abc.def": rng.random(1024, dtype=np.float32),
        "openalex:W123": rng.random(1024, dtype=np.float32),
    }
    out = tmp_path / "sub" / "expert_vectors.npz"

    save_vectors(vectors, out)
    loaded = load_vectors(out)

    assert set(loaded) == set(vectors)
    for paper_id, vector in vectors.items():
        assert loaded[paper_id].shape == (1024,)
        assert loaded[paper_id].dtype == vector.dtype
        np.testing.assert_array_equal(loaded[paper_id], vector)


def test_get_indexed_paper_ids_excludes_unindexed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Un paper de excavador.db sin chunks en el store no forma parte del corpus."""
    monkeypatch.chdir(tmp_path)  # cwd sin .env
    storage = DummyStorage([_paper("doi:10.1/a"), _paper("doi:10.1/b"), _paper("doi:10.1/fuera")])
    store = DummyChunkStore({"doi:10.1/b": ["y"], "doi:10.1/a": ["x"]})

    ids = get_indexed_paper_ids(BibliotecaSettings(), excavador_storage=storage, chunk_store=store)

    assert ids == ["doi:10.1/a", "doi:10.1/b"]


@pytest.mark.slow
def test_real_corpus_has_158_vectors() -> None:
    """Con la Biblioteca real (desde la raíz del repo): exactamente 158 vectores (E3 de fase 03)."""
    from biblioteca.embedder import get_embedder
    from biblioteca.store import ChunkStore
    from excavador.storage import Storage

    settings = BibliotecaSettings()
    storage = Storage(settings.db_path)
    store = ChunkStore(settings.chroma_dir)

    paper_ids = get_indexed_paper_ids(settings, excavador_storage=storage, chunk_store=store)
    vectors = build_representative_vectors(
        paper_ids, storage, store, get_embedder(settings.embedding_model)
    )

    assert len(vectors) == 158
