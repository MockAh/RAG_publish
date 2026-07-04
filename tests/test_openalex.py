"""Tests para excavador.apis.openalex.OpenAlexClient e invert_abstract."""

import json
import re
from pathlib import Path
from unittest.mock import ANY

import pytest
from pytest_httpx import HTTPXMock

from excavador.apis.openalex import OpenAlexClient, invert_abstract

FIXTURES_DIR = Path(__file__).parent / "fixtures"
WORKS_URL = re.compile(r"^https://api\.openalex\.org/works(\?.*)?$")


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


NEXT_CURSOR = "IlsxNjA5NDU5NzQ0MDAwLCAnVzI3NDE4MDk4MDcnXSI="


@pytest.fixture
def client() -> OpenAlexClient:
    c = OpenAlexClient(mailto="excavador@example.com")
    c._sleep = lambda seconds: None  # type: ignore[method-assign]  # evita esperas reales
    return c


def test_invert_abstract_reconstructs_repeated_word() -> None:
    page1 = _load_fixture("openalex_search_page1.json")
    inverted_index = page1["results"][0]["abstract_inverted_index"]

    abstract = invert_abstract(inverted_index)

    assert abstract == "Despite growing interest in Open Access in"


def test_invert_abstract_empty_or_none_returns_empty_string() -> None:
    assert invert_abstract(None) == ""
    assert invert_abstract({}) == ""


def test_search_paginates_two_pages_and_cuts_at_max_results(
    client: OpenAlexClient, httpx_mock: HTTPXMock
) -> None:
    page1 = _load_fixture("openalex_search_page1.json")
    page2 = _load_fixture("openalex_search_page2.json")

    httpx_mock.add_response(
        url="https://api.openalex.org/works",
        match_params={
            "search": "Bolívar Echeverría",
            "cursor": "*",
            "per-page": ANY,
            "select": ANY,
            "mailto": ANY,
        },
        json=page1,
    )
    httpx_mock.add_response(
        url="https://api.openalex.org/works",
        match_params={
            "search": "Bolívar Echeverría",
            "cursor": NEXT_CURSOR,
            "per-page": ANY,
            "select": ANY,
            "mailto": ANY,
        },
        json=page2,
    )

    hits = client.search("Bolívar Echeverría", max_results=3)

    assert len(hits) == 3
    assert len(httpx_mock.get_requests()) == 2
    assert [h.external_id for h in hits] == ["W2741809807", "W2963341561", "W3000000001"]


def test_search_cuts_within_first_page_without_extra_request(
    client: OpenAlexClient, httpx_mock: HTTPXMock
) -> None:
    page1 = _load_fixture("openalex_search_page1.json")

    httpx_mock.add_response(url=WORKS_URL, json=page1)

    hits = client.search("Bolívar Echeverría", max_results=1)

    assert len(hits) == 1
    assert len(httpx_mock.get_requests()) == 1


def test_search_doi_is_cleaned_of_prefix(
    client: OpenAlexClient, httpx_mock: HTTPXMock
) -> None:
    page1 = _load_fixture("openalex_search_page1.json")
    httpx_mock.add_response(url=WORKS_URL, json=page1)

    hits = client.search("Bolívar Echeverría", max_results=1)

    assert hits[0].doi == "10.7717/peerj.4375"
    assert not hits[0].doi.startswith("https://")


def test_enrich_returns_none_on_404(
    client: OpenAlexClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        url=re.compile(r"^https://api\.openalex\.org/works/doi:10\.9999/no-existe(\?.*)?$"),
        status_code=404,
        json=_load_fixture("openalex_work_doi_404.json"),
    )

    result = client.enrich("10.9999/no-existe")

    assert result is None


def test_all_requests_include_mailto(
    client: OpenAlexClient, httpx_mock: HTTPXMock
) -> None:
    page1 = _load_fixture("openalex_search_page1.json")
    httpx_mock.add_response(url=WORKS_URL, json=page1)
    httpx_mock.add_response(
        url=re.compile(r"^https://api\.openalex\.org/works/doi:10\.9999/no-existe(\?.*)?$"),
        status_code=404,
    )
    httpx_mock.add_response(url=WORKS_URL, json=page1)

    client.search("Bolívar Echeverría", max_results=1)
    client.enrich("10.9999/no-existe")
    client.enrich_batch(["W1", "W2"])

    requests = httpx_mock.get_requests()
    assert len(requests) == 3
    for request in requests:
        assert request.url.params.get("mailto") == "excavador@example.com"


def test_enrich_batch_60_ids_makes_two_requests(
    client: OpenAlexClient, httpx_mock: HTTPXMock
) -> None:
    ids = [f"W{i}" for i in range(60)]

    def _make_response(group: list[str]) -> dict:
        return {
            "meta": {"count": len(group), "next_cursor": None},
            "results": [
                {
                    "id": f"https://openalex.org/{oa_id}",
                    "doi": None,
                    "title": f"Título {oa_id}",
                    "display_name": f"Título {oa_id}",
                    "publication_year": 2020,
                    "type": "article",
                    "authorships": [],
                    "primary_location": None,
                    "abstract_inverted_index": None,
                    "referenced_works": [],
                    "open_access": {"is_oa": False, "oa_url": None},
                    "best_oa_location": None,
                }
                for oa_id in group
            ],
        }

    httpx_mock.add_response(url=WORKS_URL, json=_make_response(ids[:50]))
    httpx_mock.add_response(url=WORKS_URL, json=_make_response(ids[50:]))

    hits = client.enrich_batch(ids)

    requests = httpx_mock.get_requests()
    assert len(requests) == 2
    assert len(requests[0].url.params.get("filter").split("|")) == 50
    assert len(requests[1].url.params.get("filter").split("|")) == 10
    assert len(hits) == 60
