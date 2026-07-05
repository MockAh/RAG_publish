"""Tests para excavador.snowball."""

from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from excavador.models import PaperRecord, RawHit
from excavador.snowball import snowball


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


def _raw_hit(external_id: str, doi: str | None = None) -> RawHit:
    return RawHit(
        source_api="openalex",
        raw={},
        doi=doi,
        title=f"Título {external_id}",
        external_id=external_id,
    )


@pytest.fixture
def openalex() -> Mock:
    client = Mock()
    client.enrich.return_value = None
    client.get_references.return_value = []
    client.get_citing.return_value = []
    client.enrich_batch.return_value = []
    return client


def test_only_top_k_seeds_by_score_are_processed(openalex: Mock) -> None:
    seeds = [
        _record(paper_id="openalex:W1", relevance_score=0.5),
        _record(paper_id="openalex:W2", relevance_score=0.9),
        _record(paper_id="openalex:W3", relevance_score=0.7),
    ]

    snowball(seeds, openalex, k=2)

    processed_ids = {c.args[0] for c in openalex.get_references.call_args_list}
    assert processed_ids == {"W2", "W3"}
    assert openalex.get_references.call_count == 2
    assert openalex.get_citing.call_count == 2


def test_seed_with_doi_resolves_via_enrich(openalex: Mock) -> None:
    seed = _record(paper_id="doi:10.1/x", doi="10.1/x", relevance_score=0.8)
    openalex.enrich.return_value = _raw_hit("W99", doi="10.1/x")

    snowball([seed], openalex, k=1)

    openalex.enrich.assert_called_once_with("10.1/x")
    openalex.get_references.assert_called_once_with("W99")
    openalex.get_citing.assert_called_once_with("W99", max_results=100)


def test_seed_unresolvable_is_skipped_and_next_by_score_is_used(openalex: Mock) -> None:
    seeds = [
        _record(paper_id="doi:10.1/irresoluble", doi="10.1/irresoluble", relevance_score=0.9),
        _record(paper_id="openalex:W2", relevance_score=0.7),
        _record(paper_id="openalex:W3", relevance_score=0.5),
    ]
    # el DOI del primer seed no resuelve (enrich -> None); el resto no llama a enrich
    openalex.enrich.return_value = None

    snowball(seeds, openalex, k=2)

    processed_ids = {c.args[0] for c in openalex.get_references.call_args_list}
    assert processed_ids == {"W2", "W3"}


def test_references_of_all_seeds_go_to_enrich_batch_in_one_deduplicated_call(
    openalex: Mock,
) -> None:
    seeds = [
        _record(paper_id="openalex:W1", relevance_score=0.9),
        _record(paper_id="openalex:W2", relevance_score=0.8),
    ]

    def _get_references(openalex_id: str) -> list[str]:
        return {"W1": ["R1", "R2"], "W2": ["R2", "R3"]}[openalex_id]

    openalex.get_references.side_effect = _get_references

    snowball(seeds, openalex, k=2)

    openalex.enrich_batch.assert_called_once()
    (batch_ids,), _ = openalex.enrich_batch.call_args
    assert sorted(batch_ids) == ["R1", "R2", "R3"]
    assert len(batch_ids) == len(set(batch_ids))


def test_hit_in_both_directions_appears_only_once(openalex: Mock) -> None:
    seed = _record(paper_id="openalex:W1", relevance_score=0.9)
    openalex.get_references.return_value = ["R1"]
    openalex.enrich_batch.return_value = [_raw_hit("DUP")]
    openalex.get_citing.return_value = [_raw_hit("DUP"), _raw_hit("NEW")]

    hits = snowball([seed], openalex, k=1)

    external_ids = [h.external_id for h in hits]
    assert external_ids.count("DUP") == 1
    assert "NEW" in external_ids
    assert len(hits) == 2


def test_hit_matching_a_resolved_seed_is_excluded(openalex: Mock) -> None:
    seed = _record(paper_id="openalex:W1", relevance_score=0.9)
    openalex.get_references.return_value = ["W1"]
    openalex.enrich_batch.return_value = [_raw_hit("W1")]
    openalex.get_citing.return_value = [_raw_hit("W2")]

    hits = snowball([seed], openalex, k=1)

    external_ids = [h.external_id for h in hits]
    assert "W1" not in external_ids
    assert external_ids == ["W2"]


def test_logs_counts_per_direction(openalex: Mock, caplog: pytest.LogCaptureFixture) -> None:
    seeds = [
        _record(paper_id="openalex:W1", relevance_score=0.9),
        _record(paper_id="doi:10.1/irresoluble", doi="10.1/irresoluble", relevance_score=0.95),
    ]
    openalex.enrich.return_value = None
    openalex.get_references.return_value = ["R1"]
    openalex.enrich_batch.return_value = [_raw_hit("R1")]
    openalex.get_citing.return_value = [_raw_hit("C1")]

    with caplog.at_level("INFO", logger="excavador.snowball"):
        snowball(seeds, openalex, k=2)

    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "1/2" in message  # 1 de 2 seeds resueltos
    assert "1 hits hacia atrás" in message
    assert "1 hacia adelante" in message
    assert "2 tras dedup" in message
