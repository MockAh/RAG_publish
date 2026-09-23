"""Tests para excavador.pipeline.run (T11)."""

import sqlite3
from pathlib import Path
from unittest.mock import Mock

import pytest

from excavador.config import Settings
from excavador.models import RawHit
from excavador.pipeline import run
from excavador.storage import Storage


def _oa_hit(
    doi: str,
    title: str,
    year: int,
    external_id: str,
    abstract_index: dict | None = None,
    referenced_works: list[str] | None = None,
) -> RawHit:
    raw = {
        "display_name": title,
        "publication_year": year,
        "authorships": [],
        "primary_location": None,
        "abstract_inverted_index": abstract_index,
        "type": "article",
        "referenced_works": referenced_works or [],
    }
    return RawHit(source_api="openalex", raw=raw, doi=doi, title=title, external_id=external_id)


def _crossref_hit(
    doi: str, title: str | None, year: int | None, external_id: str, valid: bool = True
) -> RawHit:
    raw = {
        "DOI": doi,
        "type": "journal-article",
        "title": [title] if title else [],
        "author": [],
        "issued": {"date-parts": [[year]] if valid else [[]]},
        "container-title": [],
    }
    return RawHit(source_api="crossref", raw=raw, doi=doi, title=title, external_id=external_id)


def _s2_hit(
    doi: str,
    title: str,
    year: int,
    external_id: str,
    abstract: str = "",
    references: list[dict] | None = None,
) -> RawHit:
    raw = {
        "title": title,
        "year": year,
        "authors": [],
        "references": references or [],
        "venue": None,
        "abstract": abstract,
        "publicationTypes": ["JournalArticle"],
    }
    return RawHit(source_api="semanticscholar", raw=raw, doi=doi, title=title, external_id=external_id)


class _FakeScorer:
    """Reemplaza el encoder real por una tabla score fija paper_id -> score.

    `split_by_threshold` es la lógica real de `RelevanceScorer` (no se mockea).
    """

    def __init__(self, score_map: dict[str, float]) -> None:
        self.score_map = score_map

    def score(self, topic: str, records):
        return [
            record.model_copy(update={"relevance_score": self.score_map[record.paper_id]})
            for record in records
        ]

    @staticmethod
    def split_by_threshold(records, threshold):
        from excavador.relevance import RelevanceScorer

        return RelevanceScorer.split_by_threshold(records, threshold)


def _build_scenario(tmp_path: Path):
    """Escenario de 12 hits iniciales + 2 hits de snowball (ver docstring del test)."""
    # dup pair (mismo DOI, distinta fuente): gana openalex por desempate en dedup()
    o1 = _oa_hit("10.1/dup", "Estudio con posible duplicado", 2020, "Wdup1")
    s1 = _s2_hit("10.1/dup", "Estudio con posible duplicado (S2)", 2020, "s2dup")

    # inválido: crossref sin año
    c_inv = _crossref_hit("10.1/invalido", "Trabajo sin año", None, "10.1/invalido", valid=False)

    # 7 hits bajo umbral, repartidos entre las 3 fuentes
    low_oa_1 = _oa_hit("10.1/low1", "Bajo interés 1", 2015, "Wlow1")
    low_oa_2 = _oa_hit("10.1/low2", "Bajo interés 2", 2016, "Wlow2")
    low_oa_3 = _oa_hit("10.1/low3", "Bajo interés 3", 2017, "Wlow3")
    low_cr_1 = _crossref_hit("10.1/low4", "Bajo interés 4", 2014, "10.1/low4")
    low_cr_2 = _crossref_hit("10.1/low5", "Bajo interés 5", 2013, "10.1/low5")
    low_s2_1 = _s2_hit("10.1/low6", "Bajo interés 6", 2012, "s2low6")
    low_s2_2 = _s2_hit("10.1/low7", "Bajo interés 7", 2011, "s2low7")

    # 2 seeds de alta relevancia (más el ganador del par duplicado, también alto)
    a1 = _oa_hit(
        "10.1/a1", "Bolívar Echeverría y la crítica cultural", 2021, "Wa1",
        abstract_index={"Resumen": [0]},
    )
    a2 = _s2_hit(
        "10.1/a2", "Modernidad barroca en la obra de Echeverría", 2018, "s2a2",
        abstract="Un análisis de modernidad barroca.", references=[{"paperId": "refX"}],
    )

    # hits que aporta el snowball a partir de a1: uno duplica a a2, otro es nuevo
    dup_hit = _oa_hit("10.1/a2", "Modernidad barroca (citante)", 2018, "Wciteddup")
    new_hit = _oa_hit(
        "10.1/new", "Nuevo hallazgo por snowball", 2019, "Wnew",
        abstract_index={"Nuevo": [0], "hallazgo": [1]},
    )

    score_map = {
        "doi:10.1/dup": 0.7,
        "doi:10.1/low1": 0.1,
        "doi:10.1/low2": 0.1,
        "doi:10.1/low3": 0.1,
        "doi:10.1/low4": 0.1,
        "doi:10.1/low5": 0.1,
        "doi:10.1/low6": 0.1,
        "doi:10.1/low7": 0.1,
        "doi:10.1/a1": 0.9,
        "doi:10.1/a2": 0.6,
        "doi:10.1/new": 0.95,
    }

    openalex = Mock()
    openalex.search.return_value = [o1, low_oa_1, low_oa_2, low_oa_3, a1]
    openalex.search_exact_phrase.return_value = []
    openalex.get_references.return_value = []

    enrich_map = {
        "10.1/dup": RawHit(
            source_api="openalex", raw={}, doi="10.1/dup", title="x", external_id="Wdupseed"
        ),
        "10.1/a1": RawHit(
            source_api="openalex", raw={}, doi="10.1/a1", title="x", external_id="Wa1"
        ),
        "10.1/a2": RawHit(
            source_api="openalex", raw={}, doi="10.1/a2", title="x", external_id="Wa2seed"
        ),
    }
    openalex.enrich.side_effect = lambda doi: enrich_map.get(doi)

    def _get_citing(openalex_id: str, max_results: int = 100):
        if openalex_id == "Wa1":
            return [dup_hit, new_hit]
        return []

    openalex.get_citing.side_effect = _get_citing

    crossref = Mock()
    crossref.search.return_value = [c_inv, low_cr_1, low_cr_2]

    s2 = Mock()
    s2.search.return_value = [s1, low_s2_1, low_s2_2, a2]

    scorer = _FakeScorer(score_map)

    settings = Settings(
        openalex_mailto="excavador@example.com",
        db_path=tmp_path / "excavador.db",
        pdf_dir=tmp_path / "pdfs",
        relevance_threshold=0.35,
        snowball_k=15,
    )
    storage = Storage(settings.db_path)

    return {
        "tema": "Bolívar Echeverría",
        "settings": settings,
        "storage": storage,
        "openalex": openalex,
        "crossref": crossref,
        "s2": s2,
        "scorer": scorer,
    }


def _run(scenario: dict, max_papers: int):
    return run(
        scenario["tema"],
        max_papers,
        scenario["settings"],
        openalex=scenario["openalex"],
        crossref=scenario["crossref"],
        s2=scenario["s2"],
        scorer=scenario["scorer"],
        storage=scenario["storage"],
    )


def test_pipeline_counts_discarded_reasons_and_idempotent_rerun(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Escenario de 12 hits iniciales (1 inválido, 2 duplicados, 7 bajo umbral, 2 seeds
    de alta relevancia) + 2 hits de snowball (1 duplicado de un aceptado, 1 nuevo válido).

    `max_papers` generoso (no trunca) para poder verificar la idempotencia real de una
    segunda corrida idéntica sin la interacción con el corte (ver `test_pipeline_respects_max_papers_cutoff`).
    """
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo
    scenario = _build_scenario(tmp_path)

    stats = _run(scenario, max_papers=10)

    assert stats.raw_hits == 12
    assert stats.invalid == 1
    assert stats.duplicates == 2  # par duplicado inicial + duplicado aportado por snowball
    assert stats.low_relevance == 7
    assert stats.snowball_raw_hits == 2
    assert stats.accepted == 4  # dup-winner, a1, a2, nuevo de snowball
    assert stats.with_pdf == 0
    assert stats.pct_pdf == 0.0
    assert stats.pct_doi == 1.0

    storage = scenario["storage"]
    assert storage.count() == 4
    assert storage.get_paper("doi:10.1/new") is not None
    assert storage.get_paper("doi:10.1/a1") is not None
    assert storage.get_paper("doi:10.1/a2") is not None
    assert storage.get_paper("doi:10.1/dup") is not None

    conn = sqlite3.connect(scenario["settings"].db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT paper_id, discard_reason FROM papers_discarded").fetchall()
    reasons = {row["paper_id"]: row["discard_reason"] for row in rows}
    conn.close()

    assert len(reasons) == 10  # 1 inválido + 2 duplicados + 7 bajo umbral
    assert reasons["doi:10.1/invalido"] == "invalid_record"
    assert reasons["doi:10.1/dup"] == "duplicate"  # el perdedor (s1) comparte paper_id con el ganador
    assert reasons["doi:10.1/a2"] == "duplicate"  # el hit de snowball que duplica a a2
    for i in range(1, 8):
        assert reasons[f"doi:10.1/low{i}"] == "low_relevance"

    # segunda corrida idéntica: todo ya está en known_dois -> no cambia storage.count()
    stats_2 = _run(scenario, max_papers=10)

    assert storage.count() == 4
    assert stats_2.accepted == 0


def test_pipeline_respects_max_papers_cutoff(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """El corte por `max_papers` se aplica ANTES de descargar, ordenando por score."""
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo
    scenario = _build_scenario(tmp_path)

    stats = _run(scenario, max_papers=2)

    assert stats.accepted == 2
    storage = scenario["storage"]
    assert storage.count() == 2
    # los 2 de mayor score sobreviven: nuevo (0.95) y a1 (0.9)
    assert storage.get_paper("doi:10.1/new") is not None
    assert storage.get_paper("doi:10.1/a1") is not None
    # a2 (0.6) y el ganador del par duplicado (0.7) quedan fuera: ni guardados ni descartados
    assert storage.get_paper("doi:10.1/a2") is None
    assert storage.get_paper("doi:10.1/dup") is None
