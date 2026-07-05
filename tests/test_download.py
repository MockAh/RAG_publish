"""Tests para excavador.download.download_pdf."""

from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock

from excavador.download import download_pdf
from excavador.models import PaperRecord


def _record(**overrides) -> PaperRecord:
    base = dict(
        paper_id="doi:10.1234/abc",
        doi="10.1234/abc",
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


@pytest.fixture
def client() -> httpx.Client:
    with httpx.Client() as c:
        yield c


def test_valid_pdf_download_writes_file_and_returns_path(
    tmp_path: Path, client: httpx.Client, httpx_mock: HTTPXMock
) -> None:
    record = _record()
    raw = {"best_oa_location": {"pdf_url": "https://example.com/paper.pdf"}}
    pdf_bytes = b"%PDF-1.4 contenido de prueba"
    httpx_mock.add_response(url="https://example.com/paper.pdf", content=pdf_bytes)

    result = download_pdf(record, raw, tmp_path, client)

    assert result is not None
    path = Path(result)
    assert path.exists()
    assert path.read_bytes() == pdf_bytes


def test_html_content_returns_none_no_file_and_logs_warning(
    tmp_path: Path, client: httpx.Client, httpx_mock: HTTPXMock, caplog: pytest.LogCaptureFixture
) -> None:
    record = _record()
    raw = {"best_oa_location": {"pdf_url": "https://example.com/paywall.html"}}
    httpx_mock.add_response(
        url="https://example.com/paywall.html", content=b"<html>not a pdf</html>"
    )

    with caplog.at_level("WARNING"):
        result = download_pdf(record, raw, tmp_path, client)

    assert result is None
    assert list(tmp_path.iterdir()) == []
    assert any("no-PDF" in r.message for r in caplog.records)


def test_preexisting_file_returns_path_without_any_request(
    tmp_path: Path, client: httpx.Client, httpx_mock: HTTPXMock
) -> None:
    record = _record()
    raw = {"best_oa_location": {"pdf_url": "https://example.com/paper.pdf"}}
    existing = tmp_path / "doi_10.1234_abc.pdf"
    existing.write_bytes(b"%PDF-ya existente")

    result = download_pdf(record, raw, tmp_path, client)

    assert result == str(existing)
    assert httpx_mock.get_requests() == []


def test_raw_none_returns_none_without_requests(
    tmp_path: Path, client: httpx.Client, httpx_mock: HTTPXMock
) -> None:
    record = _record()

    result = download_pdf(record, None, tmp_path, client)

    assert result is None
    assert httpx_mock.get_requests() == []


def test_precedence_prefers_best_oa_location_over_open_access(
    tmp_path: Path, client: httpx.Client, httpx_mock: HTTPXMock
) -> None:
    record = _record()
    raw = {
        "best_oa_location": {"pdf_url": "https://example.com/best.pdf"},
        "open_access": {"oa_url": "https://example.com/oa.pdf"},
    }
    httpx_mock.add_response(url="https://example.com/best.pdf", content=b"%PDF-best")

    download_pdf(record, raw, tmp_path, client)

    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    assert str(requests[0].url) == "https://example.com/best.pdf"


def test_null_pdf_url_falls_back_to_next_candidate(
    tmp_path: Path, client: httpx.Client, httpx_mock: HTTPXMock
) -> None:
    record = _record()
    raw = {
        "best_oa_location": {"pdf_url": None},
        "open_access": {"oa_url": "https://example.com/oa.pdf"},
    }
    httpx_mock.add_response(url="https://example.com/oa.pdf", content=b"%PDF-oa")

    result = download_pdf(record, raw, tmp_path, client)

    assert result is not None
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    assert str(requests[0].url) == "https://example.com/oa.pdf"


def test_connection_error_returns_none_and_logs_warning_without_raising(
    tmp_path: Path, client: httpx.Client, httpx_mock: HTTPXMock, caplog: pytest.LogCaptureFixture
) -> None:
    record = _record()
    raw = {"best_oa_location": {"pdf_url": "https://example.com/paper.pdf"}}
    httpx_mock.add_exception(httpx.ConnectError("connection refused"))

    with caplog.at_level("WARNING"):
        result = download_pdf(record, raw, tmp_path, client)

    assert result is None
    assert any("Descarga fallida" in r.message for r in caplog.records)


def test_paper_id_with_doi_produces_expected_filename(
    tmp_path: Path, client: httpx.Client, httpx_mock: HTTPXMock
) -> None:
    record = _record(paper_id="doi:10.1234/abc")
    raw = {"best_oa_location": {"pdf_url": "https://example.com/paper.pdf"}}
    httpx_mock.add_response(url="https://example.com/paper.pdf", content=b"%PDF-x")

    result = download_pdf(record, raw, tmp_path, client)

    assert result == str(tmp_path / "doi_10.1234_abc.pdf")
