"""Tests para biblioteca.__main__ (CLI, M16)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import biblioteca.__main__ as cli_main
from biblioteca.__main__ import app
from biblioteca.models import Chunk, IndexStats, ScoredChunk

runner = CliRunner()


def _isolate_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Aísla `Settings()` del `.env` real del repo: cwd en tmp_path (mismo patrón que test_cli.py)."""
    monkeypatch.chdir(tmp_path)


def _fake_index_stats() -> IndexStats:
    return IndexStats(
        papers_total=10,
        papers_indexed=8,
        papers_skipped=1,
        papers_failed=1,
        chunks_created=120,
        from_abstract_count=15,
        duration_s=126.0,
    )


def _chunk(chunk_id: str, paper_id: str, section: str, text: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        paper_id=paper_id,
        section=section,
        text=text,
        char_start=0,
        char_end=len(text),
        embedding_model="e5-test",
    )


class _FakeChunkStore:
    """Doble de `ChunkStore`: cada método devuelve valores fijados por el test que lo instancia."""

    def __init__(
        self,
        retrieve_result: list[ScoredChunk] | None = None,
        get_chunk_full_result: tuple[Chunk, bool] | None = None,
        count_result: int = 0,
        all_metadata_result: list[dict] | None = None,
    ) -> None:
        self.retrieve_result = retrieve_result or []
        self.get_chunk_full_result = get_chunk_full_result
        self.count_result = count_result
        self.all_metadata_result = all_metadata_result or []
        self.retrieve_calls: list[dict] = []

    def retrieve(self, query, top_k=8, filter_paper_ids=None, filter_sections=None, embedder=None):
        self.retrieve_calls.append(
            {"query": query, "top_k": top_k, "filter_paper_ids": filter_paper_ids, "filter_sections": filter_sections}
        )
        return self.retrieve_result

    def get_chunk_full(self, chunk_id):
        return self.get_chunk_full_result

    def count(self):
        return self.count_result

    def all_metadata(self):
        return self.all_metadata_result


def _patch_chunk_store(monkeypatch: pytest.MonkeyPatch, fake: _FakeChunkStore) -> None:
    monkeypatch.setattr(cli_main, "ChunkStore", lambda chroma_dir: fake)


def test_index_invokes_index_corpus_with_correct_params(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`index` llama a `index_corpus` con `force`, `limit` y `batch_size` correctos, y sale con código 0."""
    _isolate_env(monkeypatch, tmp_path)

    calls = {}

    def _fake_index_corpus(settings, *, force, limit, batch_size):
        calls["force"] = force
        calls["limit"] = limit
        calls["batch_size"] = batch_size
        return _fake_index_stats()

    monkeypatch.setattr(cli_main, "index_corpus", _fake_index_corpus)

    result = runner.invoke(app, ["index", "--force", "--limit", "10", "--batch-size", "16"])

    assert result.exit_code == 0
    assert calls == {"force": True, "limit": 10, "batch_size": 16}
    assert "8" in result.output  # papers_indexed
    assert "2.1 min" in result.output  # 126s / 60


def test_query_prints_results_with_abstract_mark(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`query` imprime los resultados de `retrieve` mockeado, incluida la marca `[abstract]`."""
    _isolate_env(monkeypatch, tmp_path)

    scored = [
        ScoredChunk(chunk=_chunk("p1#intro#0", "p1", "introduction", "Texto normal."), score=0.876, from_abstract=False),
        ScoredChunk(chunk=_chunk("p2#abstract#0", "p2", "abstract", "Texto degradado."), score=0.5, from_abstract=True),
    ]
    fake_store = _FakeChunkStore(retrieve_result=scored)
    _patch_chunk_store(monkeypatch, fake_store)

    result = runner.invoke(app, ["query", "un tema de prueba", "--top-k", "2"])

    assert result.exit_code == 0
    assert "0.876" in result.output
    assert "p1#intro#0" in result.output
    assert "p2#abstract#0" in result.output
    assert "[abstract]" in result.output
    assert fake_store.retrieve_calls[0]["query"] == "un tema de prueba"
    assert fake_store.retrieve_calls[0]["top_k"] == 2


def test_query_with_repeated_filters_passes_lists(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`--paper-id` y `--section` repetidos se pasan como listas a `retrieve`."""
    _isolate_env(monkeypatch, tmp_path)

    fake_store = _FakeChunkStore(retrieve_result=[])
    _patch_chunk_store(monkeypatch, fake_store)

    runner.invoke(
        app,
        [
            "query",
            "texto",
            "--paper-id",
            "p1",
            "--paper-id",
            "p2",
            "--section",
            "methods",
        ],
    )

    call = fake_store.retrieve_calls[0]
    assert call["filter_paper_ids"] == ["p1", "p2"]
    assert call["filter_sections"] == ["methods"]


def test_query_no_results_prints_clean_message(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`query` sin resultados imprime un mensaje claro, sin traza de error, y sale con 0."""
    _isolate_env(monkeypatch, tmp_path)

    _patch_chunk_store(monkeypatch, _FakeChunkStore(retrieve_result=[]))

    result = runner.invoke(app, ["query", "nada por aquí"])

    assert result.exit_code == 0
    assert result.exception is None
    assert "Sin resultados" in result.output


def test_get_missing_chunk_id_exits_nonzero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`get` con un `chunk_id` inexistente informa y sale con código distinto de 0."""
    _isolate_env(monkeypatch, tmp_path)

    _patch_chunk_store(monkeypatch, _FakeChunkStore(get_chunk_full_result=None))

    result = runner.invoke(app, ["get", "no-existe#seccion#0"])

    assert result.exit_code != 0
    assert "no-existe#seccion#0" in result.output


def test_get_existing_chunk_prints_all_fields(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`get` imprime todos los campos de C2 más `from_abstract`."""
    _isolate_env(monkeypatch, tmp_path)

    chunk = _chunk("p1#abstract#0", "p1", "abstract", "Contenido completo del chunk.")
    _patch_chunk_store(monkeypatch, _FakeChunkStore(get_chunk_full_result=(chunk, True)))

    result = runner.invoke(app, ["get", "p1#abstract#0"])

    assert result.exit_code == 0
    assert "p1#abstract#0" in result.output
    assert "paper_id: p1" in result.output
    assert "from_abstract: True" in result.output
    assert "Contenido completo del chunk." in result.output


def test_stats_on_empty_store_does_not_divide_by_zero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`stats` funciona sobre un store vacío sin dividir entre cero."""
    _isolate_env(monkeypatch, tmp_path)

    _patch_chunk_store(monkeypatch, _FakeChunkStore(count_result=0))

    result = runner.invoke(app, ["stats"])

    assert result.exit_code == 0
    assert result.exception is None
    assert "vacía" in result.output


def test_stats_computes_distinct_papers_and_average(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`stats` calcula nº de chunks, papers distintos, from_abstract y media por paper."""
    _isolate_env(monkeypatch, tmp_path)

    metadatas = [
        {"paper_id": "p1", "from_abstract": False},
        {"paper_id": "p1", "from_abstract": False},
        {"paper_id": "p2", "from_abstract": True},
    ]
    _patch_chunk_store(monkeypatch, _FakeChunkStore(count_result=3, all_metadata_result=metadatas))

    result = runner.invoke(app, ["stats"])

    assert result.exit_code == 0
    assert "Chunks totales: 3" in result.output
    assert "Papers distintos indexados: 2" in result.output
    assert "Chunks desde abstract: 1" in result.output
    assert "1.5" in result.output
