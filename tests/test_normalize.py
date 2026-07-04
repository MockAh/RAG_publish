"""Tests para excavador.normalize."""

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

from excavador.models import PaperRecord, RawHit
from excavador.normalize import (
    canonical_enrich,
    normalize_crossref,
    normalize_openalex,
    normalize_semanticscholar,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _openalex_hit(raw: dict) -> RawHit:
    doi = raw.get("doi")
    if doi:
        doi = doi.removeprefix("https://doi.org/")
    return RawHit(
        source_api="openalex",
        raw=raw,
        doi=doi,
        title=raw.get("display_name"),
        external_id=raw.get("id", "").rsplit("/", 1)[-1],
    )


def test_normalize_openalex_valid_hit() -> None:
    work = _load_fixture("openalex_search_page1.json")["results"][0]
    hit = _openalex_hit(work)

    record = normalize_openalex(hit)

    assert record is not None
    assert record.paper_id == "doi:10.7717/peerj.4375"
    assert record.doi == "10.7717/peerj.4375"
    assert record.title == work["display_name"]
    assert record.authors == ["Heather Piwowar"]
    assert record.year == 2018
    assert record.venue == "PeerJ"
    assert record.abstract == "Despite growing interest in Open Access in"
    assert record.source_api == "openalex"
    assert record.work_type == "article"
    assert record.pdf_path is None
    assert record.relevance_score == 0.0
    assert record.references_ids == ["openalex:W2100"]


def test_normalize_openalex_missing_year_returns_none() -> None:
    work = copy.deepcopy(_load_fixture("openalex_search_page1.json")["results"][0])
    work["publication_year"] = None
    hit = _openalex_hit(work)

    assert normalize_openalex(hit) is None


def test_normalize_crossref_valid_hit() -> None:
    raw = _load_fixture("crossref_work.json")
    hit = RawHit(
        source_api="crossref",
        raw=raw,
        doi=raw["DOI"],
        title=raw["title"][0],
        external_id=raw["DOI"],
    )

    record = normalize_crossref(hit)

    assert record is not None
    assert record.paper_id == "doi:10.1016/j.example.2020.01.001"
    assert record.title == "La filosofía de la cultura en Bolívar Echeverría"
    assert record.authors == ["Ana Pérez", "Luis Gómez"]
    assert record.year == 2020
    assert record.venue == "Revista de Estudios Latinoamericanos"
    assert record.abstract == "Este artículo analiza la obra de Bolívar Echeverría."
    assert record.source_api == "crossref"
    assert record.work_type == "article"


def test_normalize_crossref_missing_title_returns_none() -> None:
    raw = copy.deepcopy(_load_fixture("crossref_work.json"))
    raw["title"] = []
    hit = RawHit(source_api="crossref", raw=raw, doi=raw["DOI"], title=None, external_id=raw["DOI"])

    assert normalize_crossref(hit) is None


def test_normalize_semanticscholar_valid_hit() -> None:
    raw = _load_fixture("semanticscholar_paper.json")
    hit = RawHit(
        source_api="semanticscholar",
        raw=raw,
        doi=raw["externalIds"]["DOI"],
        title=raw["title"],
        external_id=raw["paperId"],
    )

    record = normalize_semanticscholar(hit)

    assert record is not None
    assert record.paper_id == "doi:10.1000/s2.example"
    assert record.title == "Modernidad barroca y valor de uso"
    assert record.authors == ["Carlos Ruiz"]
    assert record.year == 2015
    assert record.venue == "Latin American Perspectives"
    assert record.abstract == "Un análisis del concepto de modernidad barroca."
    assert record.source_api == "semanticscholar"
    assert record.work_type == "article"
    assert record.references_ids == ["semanticscholar:ref1", "semanticscholar:ref2"]


def _make_record(**overrides) -> PaperRecord:
    base = dict(
        paper_id="semanticscholar:xyz",
        doi=None,
        title="Un título cualquiera",
        authors=["Autor Uno"],
        year=2021,
        venue="Existing Venue",
        abstract="",
        source_api="semanticscholar",
        work_type="other",
        pdf_path=None,
        relevance_score=0.0,
        references_ids=[],
        ingested_at=datetime.now(timezone.utc),
    )
    base.update(overrides)
    return PaperRecord(**base)


def test_canonical_enrich_fills_empty_fields_without_overwriting_venue() -> None:
    record = _make_record()
    work = _load_fixture("openalex_search_page1.json")["results"][0]
    raw_enriched = _openalex_hit(work)

    enriched = canonical_enrich(record, raw_enriched)

    assert enriched.abstract == "Despite growing interest in Open Access in"
    assert enriched.venue == "Existing Venue"  # no se pisa el ya presente
    assert enriched.references_ids == ["openalex:W2100"]
    assert enriched.work_type == "article"


def test_canonical_enrich_with_none_returns_record_unchanged() -> None:
    record = _make_record()

    result = canonical_enrich(record, None)

    assert result == record
