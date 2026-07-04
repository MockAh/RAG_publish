"""Tests para excavador.storage.Storage."""

from datetime import datetime, timezone
from pathlib import Path

from excavador.models import DiscardedRecord, PaperRecord
from excavador.storage import Storage


def _paper(**overrides) -> PaperRecord:
    kwargs = dict(
        paper_id="doi:10.1234/abc",
        doi="10.1234/abc",
        title="La definición de la cultura",
        authors=["Bolívar Echeverría"],
        year=1998,
        venue="Itaca",
        abstract="Un análisis sobre la noción de cultura y modernidad barroca.",
        source_api="openalex",
        work_type="book",
        pdf_path=None,
        relevance_score=0.87,
        references_ids=["openalex:W1", "openalex:W2"],
        ingested_at=datetime(2026, 7, 4, tzinfo=timezone.utc),
    )
    kwargs.update(overrides)
    return PaperRecord(**kwargs)


def test_upsert_paper_twice_does_not_duplicate(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "excavador.db")
    p = _paper()

    storage.upsert_paper(p)
    storage.upsert_paper(p)

    assert storage.count() == 1


def test_upsert_paper_roundtrip_preserves_accents_and_enye(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "excavador.db")
    p = _paper()

    storage.upsert_paper(p)
    restored = storage.get_paper(p.paper_id)

    assert restored == p
    assert restored.title == "La definición de la cultura"
    assert restored.authors == ["Bolívar Echeverría"]


def test_get_paper_unknown_id_returns_none(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "excavador.db")

    assert storage.get_paper("doi:no-existe") is None


def test_known_dois_ignores_records_without_doi(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "excavador.db")
    with_doi = _paper(paper_id="doi:10.1234/abc", doi="10.1234/abc")
    without_doi = _paper(paper_id="openalex:W999", doi=None)

    storage.upsert_paper(with_doi)
    storage.upsert_paper(without_doi)

    assert storage.known_dois() == {"10.1234/abc"}


def test_constructor_creates_parent_dir(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "dir" / "excavador.db"

    Storage(db_path)

    assert db_path.parent.is_dir()


def test_upsert_discarded_and_all_papers(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "excavador.db")
    discarded = DiscardedRecord(**_paper().model_dump(), discard_reason="low_relevance")

    storage.upsert_discarded(discarded)

    assert storage.all_papers() == []
    assert storage.count() == 0
