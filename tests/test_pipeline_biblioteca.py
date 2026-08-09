"""Tests para biblioteca.pipeline.index_corpus."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from biblioteca.config import Settings
from biblioteca.grobid import GrobidError
from biblioteca.pipeline import index_corpus
from biblioteca.store import ChunkStore
from excavador.models import PaperRecord
from excavador.storage import Storage

FIXTURE_TEI = Path(__file__).parent / "fixtures" / "grobid_sample.tei.xml"

_ABSTRACT_CORTO = (
    "Un resumen suficientemente extenso para producir al menos un chunk citable "
    "sobre modernidad y cultura barroca en América Latina, con varias oraciones "
    "que aportan contexto semántico adicional al título del trabajo."
)


class _FakeGrobid:
    """Doble de GrobidClient: devuelve la fixture TEI, salvo para los paper_id en `fail_for`."""

    def __init__(self, fail_for: set[str] | None = None) -> None:
        self.fail_for = fail_for or set()
        self.calls: list[Path] = []

    def process_fulltext(self, pdf_path: Path, force: bool = False) -> Path:
        self.calls.append(pdf_path)
        if pdf_path.stem in self.fail_for:
            raise GrobidError(f"GROBID falso: fallo simulado para {pdf_path.name}")
        return FIXTURE_TEI


class _FakeEmbedder:
    """Doble de Embedder: vectores deterministas de dimensión fija, sin cargar el modelo real."""

    def __init__(self, dim: int = 4) -> None:
        self.dim = dim
        self.calls: list[list[str]] = []

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[float((hash(text) >> i) % 7) for i in range(self.dim)] for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return [float((hash(text) >> i) % 7) for i in range(self.dim)]


def _paper(paper_id: str, *, pdf_path: str | None, abstract: str = _ABSTRACT_CORTO) -> PaperRecord:
    return PaperRecord(
        paper_id=paper_id,
        doi=None,
        title=f"Título de {paper_id}",
        authors=["Autora de Prueba"],
        year=2020,
        venue="Revista de prueba",
        abstract=abstract,
        source_api="openalex",
        work_type="article",
        pdf_path=pdf_path,
        relevance_score=0.9,
        references_ids=[],
        ingested_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _make_pdf(tmp_path: Path, name: str) -> Path:
    path = tmp_path / "pdfs" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4 contenido de prueba")
    return path


def _settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo (F2)
    return Settings(
        db_path=tmp_path / "excavador.db",
        pdf_dir=tmp_path / "pdfs",
        tei_dir=tmp_path / "tei",
        text_dir=tmp_path / "text",
        chroma_dir=tmp_path / "chroma",
        embedding_model="e5-test",
    )


def _populate_storage(db_path: Path, papers: list[PaperRecord]) -> None:
    storage = Storage(db_path)
    for paper in papers:
        storage.upsert_paper(paper)


def _corpus_mixto(tmp_path: Path) -> list[PaperRecord]:
    pdf_a = _make_pdf(tmp_path, "pdf_a.pdf")
    pdf_b = _make_pdf(tmp_path, "pdf_b.pdf")
    return [
        _paper("doi:pdf-a", pdf_path=str(pdf_a)),
        _paper("doi:pdf-b", pdf_path=str(pdf_b)),
        _paper("doi:abs-c", pdf_path=None),
        _paper("doi:abs-d", pdf_path=None),
    ]


def test_corpus_mixto_todos_quedan_indexados(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    papers = _corpus_mixto(tmp_path)
    _populate_storage(tmp_path / "excavador.db", papers)
    settings = _settings(tmp_path, monkeypatch)

    stats = index_corpus(
        settings, grobid=_FakeGrobid(), store=ChunkStore(settings.chroma_dir), embedder=_FakeEmbedder()
    )

    assert stats.papers_total == 4
    assert stats.papers_indexed == 4
    assert stats.papers_skipped == 0
    assert stats.papers_failed == 0
    assert stats.chunks_created > 0
    assert stats.from_abstract_count > 0
    assert stats.from_abstract_count < stats.chunks_created
    assert stats.duration_s >= 0


def test_idempotencia_segunda_corrida_sin_force_salta_todo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    papers = _corpus_mixto(tmp_path)
    _populate_storage(tmp_path / "excavador.db", papers)
    settings = _settings(tmp_path, monkeypatch)
    store = ChunkStore(settings.chroma_dir)

    index_corpus(settings, grobid=_FakeGrobid(), store=store, embedder=_FakeEmbedder())
    count_after_first = store.count()

    stats_segunda = index_corpus(settings, grobid=_FakeGrobid(), store=store, embedder=_FakeEmbedder())

    assert stats_segunda.papers_skipped == 4
    assert stats_segunda.papers_indexed == 0
    assert store.count() == count_after_first


def test_force_reindexa_sin_duplicar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    papers = _corpus_mixto(tmp_path)
    _populate_storage(tmp_path / "excavador.db", papers)
    settings = _settings(tmp_path, monkeypatch)
    store = ChunkStore(settings.chroma_dir)

    index_corpus(settings, grobid=_FakeGrobid(), store=store, embedder=_FakeEmbedder())
    count_after_first = store.count()

    stats_force = index_corpus(
        settings, force=True, grobid=_FakeGrobid(), store=store, embedder=_FakeEmbedder()
    )

    assert stats_force.papers_indexed == 4
    assert stats_force.papers_skipped == 0
    assert store.count() == count_after_first


def test_chunks_abstract_marcan_from_abstract_true_y_pdf_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    papers = _corpus_mixto(tmp_path)
    _populate_storage(tmp_path / "excavador.db", papers)
    settings = _settings(tmp_path, monkeypatch)
    store = ChunkStore(settings.chroma_dir)
    embedder = _FakeEmbedder()

    index_corpus(settings, grobid=_FakeGrobid(), store=store, embedder=embedder)

    pdf_results = store.retrieve("modernidad", top_k=50, filter_paper_ids=["doi:pdf-a"], embedder=embedder)
    abstract_results = store.retrieve(
        "modernidad", top_k=50, filter_paper_ids=["doi:abs-c"], embedder=embedder
    )

    assert pdf_results
    assert abstract_results
    assert all(not r.from_abstract for r in pdf_results)
    assert all(r.from_abstract for r in abstract_results)


def test_grobid_error_cae_a_abstract_y_cuenta_fallo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_a = _make_pdf(tmp_path, "pdf_a.pdf")
    pdf_fail = _make_pdf(tmp_path, "pdf_fail.pdf")
    papers = [
        _paper("doi:pdf-a", pdf_path=str(pdf_a)),
        _paper("doi:pdf-fail", pdf_path=str(pdf_fail)),
    ]
    _populate_storage(tmp_path / "excavador.db", papers)
    settings = _settings(tmp_path, monkeypatch)
    store = ChunkStore(settings.chroma_dir)
    embedder = _FakeEmbedder()

    stats = index_corpus(
        settings, grobid=_FakeGrobid(fail_for={"pdf_fail"}), store=store, embedder=embedder
    )

    assert stats.papers_failed == 1
    assert stats.papers_indexed == 2
    assert store.has_paper("doi:pdf-fail")

    results = store.retrieve("prueba", top_k=50, filter_paper_ids=["doi:pdf-fail"], embedder=embedder)
    assert results
    assert all(r.from_abstract for r in results)


def test_pdf_path_inexistente_usa_ruta_abstract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    papers = [_paper("doi:pdf-perdido", pdf_path=str(tmp_path / "pdfs" / "no_existe.pdf"))]
    _populate_storage(tmp_path / "excavador.db", papers)
    settings = _settings(tmp_path, monkeypatch)
    store = ChunkStore(settings.chroma_dir)
    embedder = _FakeEmbedder()
    grobid = _FakeGrobid()

    stats = index_corpus(settings, grobid=grobid, store=store, embedder=embedder)

    assert stats.papers_indexed == 1
    assert stats.papers_failed == 0
    assert grobid.calls == []  # nunca se llamó a GROBID: el PDF no existe

    results = store.retrieve("prueba", top_k=50, filter_paper_ids=["doi:pdf-perdido"], embedder=embedder)
    assert results
    assert all(r.from_abstract for r in results)


def test_archivos_texto_plano_en_text_dir_para_ambas_rutas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    papers = _corpus_mixto(tmp_path)
    _populate_storage(tmp_path / "excavador.db", papers)
    settings = _settings(tmp_path, monkeypatch)

    index_corpus(
        settings, grobid=_FakeGrobid(), store=ChunkStore(settings.chroma_dir), embedder=_FakeEmbedder()
    )

    assert (settings.text_dir / "doi_pdf-a.txt").exists()
    assert (settings.text_dir / "doi_pdf-b.txt").exists()
    assert (settings.text_dir / "doi_abs-c.txt").exists()
    assert (settings.text_dir / "doi_abs-d.txt").exists()


def test_limit_corta_el_numero_de_papers_procesados(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    papers = _corpus_mixto(tmp_path)
    _populate_storage(tmp_path / "excavador.db", papers)
    settings = _settings(tmp_path, monkeypatch)

    stats = index_corpus(
        settings,
        limit=2,
        grobid=_FakeGrobid(),
        store=ChunkStore(settings.chroma_dir),
        embedder=_FakeEmbedder(),
    )

    assert stats.papers_total == 2
    assert stats.papers_indexed == 2
