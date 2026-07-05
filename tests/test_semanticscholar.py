"""Tests para excavador.apis.semanticscholar.SemanticScholarClient."""

import json
import re
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from excavador.apis.semanticscholar import SemanticScholarClient
from excavador.normalize import normalize_semanticscholar

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SEARCH_URL = re.compile(r"^https://api\.semanticscholar\.org/graph/v1/paper/search(\?.*)?$")
REFERENCES_URL = re.compile(
    r"^https://api\.semanticscholar\.org/graph/v1/paper/abc123/references(\?.*)?$"
)


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _make_client(api_key: str | None = None) -> SemanticScholarClient:
    c = SemanticScholarClient(api_key=api_key)
    c._sleep = lambda seconds: None  # type: ignore[method-assign]  # evita esperas reales
    return c


@pytest.fixture
def client() -> SemanticScholarClient:
    return _make_client()


def test_search_returns_rawhits_with_external_id_doi_and_title(
    client: SemanticScholarClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(url=SEARCH_URL, json=_load_fixture("semanticscholar_search.json"))

    hits = client.search("Bolívar Echeverría", max_results=2)

    assert len(hits) == 2
    assert hits[0].external_id == "abc123"
    assert hits[0].doi == "10.1000/s2.example"
    assert hits[0].title == "Modernidad barroca y valor de uso"
    assert hits[1].doi is None


def test_doi_is_lowercased(client: SemanticScholarClient, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=SEARCH_URL, json=_load_fixture("semanticscholar_search.json"))

    hits = client.search("Bolívar Echeverría", max_results=1)

    assert hits[0].doi == hits[0].doi.lower()
    assert hits[0].doi == "10.1000/s2.example"


def test_search_without_api_key_omits_header(
    client: SemanticScholarClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(url=SEARCH_URL, json=_load_fixture("semanticscholar_search.json"))

    client.search("Bolívar Echeverría", max_results=1)

    request = httpx_mock.get_requests()[0]
    assert "x-api-key" not in request.headers


def test_search_with_api_key_includes_header(httpx_mock: HTTPXMock) -> None:
    client = _make_client(api_key="secret-key")
    httpx_mock.add_response(url=SEARCH_URL, json=_load_fixture("semanticscholar_search.json"))

    client.search("Bolívar Echeverría", max_results=1)

    request = httpx_mock.get_requests()[0]
    assert request.headers["x-api-key"] == "secret-key"


def test_get_references_ignores_none_cited_paper(
    client: SemanticScholarClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        url=REFERENCES_URL, json=_load_fixture("semanticscholar_references.json")
    )

    references = client.get_references("abc123")

    assert references == ["ref1", "ref3"]


def test_search_then_normalize_semanticscholar_produces_valid_paper_record(
    client: SemanticScholarClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(url=SEARCH_URL, json=_load_fixture("semanticscholar_search.json"))

    hits = client.search("Bolívar Echeverría", max_results=2)
    records = [normalize_semanticscholar(hit) for hit in hits]

    assert records[0] is not None
    assert records[0].title == "Modernidad barroca y valor de uso"
    assert records[0].doi == "10.1000/s2.example"
    assert records[0].paper_id == "doi:10.1000/s2.example"
    assert records[0].source_api == "semanticscholar"
    assert records[0].work_type == "article"
    assert records[0].references_ids == [
        "semanticscholar:ref1",
        "semanticscholar:ref2",
    ]

    # segundo hit sin DOI: paper_id cae al fallback "<source_api>:<external_id>"
    assert records[1] is not None
    assert records[1].doi is None
    assert records[1].paper_id == "semanticscholar:def456"
