"""Tests para excavador.apis.crossref.CrossrefClient."""

import json
import re
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from excavador.apis.crossref import CrossrefClient
from excavador.normalize import normalize_crossref

FIXTURES_DIR = Path(__file__).parent / "fixtures"
WORKS_URL = re.compile(r"^https://api\.crossref\.org/works(\?.*)?$")


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture
def client() -> CrossrefClient:
    c = CrossrefClient(mailto="excavador@example.com")
    c._sleep = lambda seconds: None  # type: ignore[method-assign]  # evita esperas reales
    return c


def test_search_returns_rawhits_with_doi_and_title(
    client: CrossrefClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(url=WORKS_URL, json=_load_fixture("crossref_search.json"))

    hits = client.search("Bolívar Echeverría", max_results=2)

    assert len(hits) == 2
    assert hits[0].doi == "10.1016/j.example.2020.01.001"
    assert hits[0].external_id == "10.1016/j.example.2020.01.001"
    assert hits[0].title == "La filosofía de la cultura en Bolívar Echeverría"
    # segundo item viene con title: [] -> None
    assert hits[1].title is None


def test_user_agent_contains_mailto(
    client: CrossrefClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(url=WORKS_URL, json=_load_fixture("crossref_search.json"))

    client.search("Bolívar Echeverría", max_results=2)

    request = httpx_mock.get_requests()[0]
    assert request.headers["User-Agent"] == "excavador/0.1 (mailto:excavador@example.com)"


def test_enrich_returns_none_on_404(
    client: CrossrefClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        url=re.compile(r"^https://api\.crossref\.org/works/10\.9999/no-existe(\?.*)?$"),
        status_code=404,
    )

    result = client.enrich("10.9999/no-existe")

    assert result is None


def test_search_then_normalize_crossref_produces_valid_paper_record(
    client: CrossrefClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(url=WORKS_URL, json=_load_fixture("crossref_search.json"))

    hits = client.search("Bolívar Echeverría", max_results=2)
    records = [normalize_crossref(hit) for hit in hits]

    # el primer hit tiene título y año -> PaperRecord válido
    assert records[0] is not None
    assert records[0].title == "La filosofía de la cultura en Bolívar Echeverría"
    assert records[0].doi == "10.1016/j.example.2020.01.001"
    assert records[0].paper_id == "doi:10.1016/j.example.2020.01.001"
    assert records[0].source_api == "crossref"
    assert records[0].work_type == "article"

    # el segundo hit no tiene título -> normalize_crossref devuelve None
    assert records[1] is None
