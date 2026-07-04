"""Tests para excavador.apis.base.ApiClient."""

from unittest.mock import Mock

import httpx
import pytest
from pytest_httpx import HTTPXMock

from excavador.apis.arxiv import ArxivClient
from excavador.apis.base import ApiClient
from excavador.apis.pubmed import PubmedClient
from excavador.models import RawHit


class _DummyClient(ApiClient):
    """Subclase concreta mínima de ApiClient para tests."""

    source_api = "openalex"
    min_interval_s = 0.05

    def search(self, query: str, max_results: int = 50) -> list[RawHit]:
        raise NotImplementedError


def test_rate_limit_sleeps_between_consecutive_calls(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url="https://example.com/a", json={"ok": True})
    httpx_mock.add_response(url="https://example.com/a", json={"ok": True})

    client = _DummyClient()
    sleep_mock = Mock()
    client._sleep = sleep_mock  # type: ignore[method-assign]

    client._get("https://example.com/a", {})
    client._get("https://example.com/a", {})

    positive_calls = [c for c in sleep_mock.call_args_list if c.args[0] > 0]
    assert positive_calls, "se esperaba al menos una espera positiva entre llamadas consecutivas"


def test_429_then_200_succeeds(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url="https://example.com/b", status_code=429)
    httpx_mock.add_response(url="https://example.com/b", json={"value": 42})

    client = _DummyClient()
    client._sleep = Mock()  # type: ignore[method-assign]  # evita esperar el backoff real

    result = client._get("https://example.com/b", {})

    assert result == {"value": 42}


def test_404_raises_immediately_without_retry(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url="https://example.com/c", status_code=404)

    client = _DummyClient()
    client._sleep = Mock()  # type: ignore[method-assign]

    with pytest.raises(httpx.HTTPStatusError):
        client._get("https://example.com/c", {})

    assert len(httpx_mock.get_requests()) == 1


def test_arxiv_stub_raises_not_implemented() -> None:
    client = ArxivClient()
    with pytest.raises(NotImplementedError):
        client.search("recepción crítica de Bolívar Echeverría")


def test_pubmed_stub_raises_not_implemented() -> None:
    client = PubmedClient()
    with pytest.raises(NotImplementedError):
        client.search("recepción crítica de Bolívar Echeverría")
