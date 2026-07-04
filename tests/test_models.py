"""Tests para excavador.models: PaperRecord, RawHit, DiscardedRecord."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from excavador.models import DiscardedRecord, PaperRecord, RawHit


def _base_paper_kwargs() -> dict:
    return dict(
        paper_id="doi:10.1234/abc",
        doi="10.1234/abc",
        title="La definición de la cultura",
        authors=["Bolívar Echeverría"],
        year=1998,
        venue="Itaca",
        abstract="Un análisis sobre la noción de cultura y modernidad barroca en América Latina.",
        source_api="openalex",
        work_type="book",
        pdf_path=None,
        relevance_score=0.87,
        references_ids=["openalex:W1", "openalex:W2"],
        ingested_at=datetime(2026, 7, 4, tzinfo=timezone.utc),
    )


def test_paper_record_roundtrip_json() -> None:
    record = PaperRecord(**_base_paper_kwargs())

    restored = PaperRecord.model_validate_json(record.model_dump_json())

    assert restored == record


def test_paper_record_roundtrip_preserves_accents_and_enye() -> None:
    record = PaperRecord(**_base_paper_kwargs())

    restored = PaperRecord.model_validate_json(record.model_dump_json())

    assert restored.title == "La definición de la cultura"
    assert restored.authors == ["Bolívar Echeverría"]


@pytest.mark.parametrize("bad_score", [-0.1, 1.1])
def test_paper_record_rejects_relevance_score_out_of_range(bad_score: float) -> None:
    kwargs = _base_paper_kwargs()
    kwargs["relevance_score"] = bad_score

    with pytest.raises(ValidationError):
        PaperRecord(**kwargs)


def test_raw_hit_roundtrip_json() -> None:
    hit = RawHit(
        source_api="openalex",
        raw={"id": "W123", "display_name": "Ñoño y la modernidad barroca"},
        doi="10.1234/xyz",
        title="Ñoño y la modernidad barroca",
        external_id="W123",
    )

    restored = RawHit.model_validate_json(hit.model_dump_json())

    assert restored == hit
    assert restored.title == "Ñoño y la modernidad barroca"


def test_discarded_record_roundtrip_json() -> None:
    discarded = DiscardedRecord(
        **_base_paper_kwargs(),
        discard_reason="low_relevance",
    )

    restored = DiscardedRecord.model_validate_json(discarded.model_dump_json())

    assert restored == discarded
    assert restored.discard_reason == "low_relevance"
