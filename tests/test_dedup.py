"""Tests para excavador.dedup."""

from datetime import datetime, timezone

from excavador.dedup import dedup, normalize_doi, normalize_title
from excavador.models import PaperRecord


def _record(**overrides) -> PaperRecord:
    base = dict(
        paper_id="openalex:W1",
        doi=None,
        title="Un título cualquiera",
        authors=["Autor Uno"],
        year=2020,
        venue=None,
        abstract="",
        source_api="openalex",
        work_type="article",
        pdf_path=None,
        relevance_score=0.0,
        references_ids=[],
        ingested_at=datetime.now(timezone.utc),
    )
    base.update(overrides)
    return PaperRecord(**base)


def test_normalize_doi_strips_prefix_case_and_spaces() -> None:
    assert normalize_doi("  HTTPS://DOI.ORG/10.1000/Example  ") == "10.1000/example"
    assert normalize_doi("10.1000/Example") == "10.1000/example"
    assert normalize_doi("doi:10.1000/Example") == "10.1000/example"


def test_normalize_title_ignores_case_and_accents() -> None:
    a = normalize_title("La definición de la cultura")
    b = normalize_title("La Definición de la Cultura")
    c = normalize_title("la definicion de la cultura")
    assert a == b == c == "la definicion de la cultura"


def test_dedup_same_doi_different_case_and_prefix_is_one_unique() -> None:
    r1 = _record(paper_id="doi:10.1000/example", doi="10.1000/Example")
    r2 = _record(paper_id="doi:10.1000/example2", doi="HTTPS://DOI.ORG/10.1000/EXAMPLE")

    uniques, duplicates = dedup([r1, r2])

    assert len(uniques) == 1
    assert len(duplicates) == 1


def test_dedup_same_title_with_and_without_accents_same_year_is_one_unique() -> None:
    r1 = _record(title="La definición de la cultura", year=2015)
    r2 = _record(title="la definicion de la cultura", year=2015)

    uniques, duplicates = dedup([r1, r2])

    assert len(uniques) == 1
    assert len(duplicates) == 1


def test_dedup_same_title_different_year_is_two_uniques() -> None:
    r1 = _record(title="La definición de la cultura", year=2015)
    r2 = _record(title="La definición de la cultura", year=2018)

    uniques, duplicates = dedup([r1, r2])

    assert len(uniques) == 2
    assert len(duplicates) == 0


def test_dedup_title_with_enye_matches_version_without_enye() -> None:
    r1 = _record(title="Diseño y modernidad", year=2010)
    r2 = _record(title="Diseno y modernidad", year=2010)

    uniques, duplicates = dedup([r1, r2])

    assert len(uniques) == 1
    assert len(duplicates) == 1


def test_dedup_winner_is_the_most_complete_record() -> None:
    incomplete = _record(
        title="Recepción crítica de Echeverría", year=2012, venue=None, abstract=""
    )
    complete = _record(
        title="Recepción crítica de Echeverría",
        year=2012,
        venue="Revista X",
        abstract="Un abstract con contenido.",
    )

    uniques, duplicates = dedup([incomplete, complete])

    assert len(uniques) == 1
    winner = uniques[0]
    assert winner.venue == "Revista X"
    assert winner.abstract == "Un abstract con contenido."
    assert duplicates == [incomplete]


def test_dedup_winner_merges_union_of_references_ids() -> None:
    r1 = _record(
        title="Recepción crítica de Echeverría",
        year=2012,
        references_ids=["openalex:W1", "openalex:W2"],
    )
    r2 = _record(
        title="Recepción crítica de Echeverría",
        year=2012,
        venue="Revista X",
        references_ids=["openalex:W2", "openalex:W3"],
    )

    uniques, duplicates = dedup([r1, r2])

    assert len(uniques) == 1
    # r2 gana por venue (más completo); conserva la unión sin duplicados, orden estable
    assert uniques[0].references_ids == ["openalex:W1", "openalex:W2", "openalex:W3"]


def test_dedup_doi_record_and_no_doi_record_same_title_year_do_not_merge() -> None:
    # Deliberado: claves de agrupación distintas ("doi", ...) vs ("title", ..., year).
    # canonical_enrich (T5) minimiza este caso completando el DOI antes de deduplicar.
    with_doi = _record(
        doi="10.1000/example", title="Recepción crítica de Echeverría", year=2012
    )
    without_doi = _record(
        doi=None, title="Recepción crítica de Echeverría", year=2012
    )

    uniques, duplicates = dedup([with_doi, without_doi])

    assert len(uniques) == 2
    assert len(duplicates) == 0
