"""Tests para biblioteca.grobid.GrobidClient."""

from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock

from biblioteca.grobid import GrobidClient, GrobidError

BASE_URL = "http://localhost:8070"


@pytest.fixture
def client(tmp_path: Path) -> GrobidClient:
    return GrobidClient(base_url=BASE_URL, tei_dir=tmp_path / "tei", timeout_s=5.0)


def _pdf(tmp_path: Path, name: str = "paper.pdf") -> Path:
    path = tmp_path / name
    path.write_bytes(b"%PDF-1.4 contenido de prueba")
    return path


def test_process_fulltext_con_tei_existente_no_hace_peticiones(
    tmp_path: Path, client: GrobidClient, httpx_mock: HTTPXMock
) -> None:
    pdf_path = _pdf(tmp_path)
    client.tei_dir.mkdir(parents=True)
    existing_tei = client.tei_path(pdf_path)
    existing_tei.write_text("<TEI>ya existente</TEI>", encoding="utf-8")

    result = client.process_fulltext(pdf_path)

    assert result == existing_tei
    assert httpx_mock.get_requests() == []


def test_process_fulltext_respuesta_valida_escribe_archivo(
    tmp_path: Path, client: GrobidClient, httpx_mock: HTTPXMock
) -> None:
    pdf_path = _pdf(tmp_path)
    tei_content = '<?xml version="1.0"?><TEI>contenido</TEI>'
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/processFulltextDocument", status_code=200, text=tei_content
    )

    result = client.process_fulltext(pdf_path)

    assert result == client.tei_path(pdf_path)
    assert result.exists()
    assert result.read_text(encoding="utf-8") == tei_content


def test_process_fulltext_status_500_levanta_grobid_error(
    tmp_path: Path, client: GrobidClient, httpx_mock: HTTPXMock
) -> None:
    pdf_path = _pdf(tmp_path)
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/processFulltextDocument",
        status_code=500,
        text="Internal Server Error",
    )

    with pytest.raises(GrobidError):
        client.process_fulltext(pdf_path)

    assert not client.tei_path(pdf_path).exists()


def test_process_fulltext_cuerpo_html_levanta_grobid_error(
    tmp_path: Path, client: GrobidClient, httpx_mock: HTTPXMock
) -> None:
    pdf_path = _pdf(tmp_path)
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/processFulltextDocument",
        status_code=200,
        text="<html><body>no soy TEI</body></html>",
    )

    with pytest.raises(GrobidError):
        client.process_fulltext(pdf_path)

    assert not client.tei_path(pdf_path).exists()


def test_is_alive_devuelve_false_si_falla_la_conexion(
    client: GrobidClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_exception(httpx.ConnectError("conexión rechazada"))

    assert client.is_alive() is False


def test_is_alive_devuelve_true_con_respuesta_true(
    client: GrobidClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(url=f"{BASE_URL}/api/isalive", status_code=200, text="true")

    assert client.is_alive() is True


@pytest.mark.slow
def test_process_fulltext_real_con_grobid(tmp_path: Path) -> None:
    """Requiere un servicio GROBID real corriendo en localhost:8070."""
    pdf_path = Path("data/pdfs/doi_10.15174_rv.v0i11.24.pdf")
    real_client = GrobidClient(base_url=BASE_URL, tei_dir=tmp_path / "tei")

    if not real_client.is_alive():
        pytest.skip("GROBID no está disponible en localhost:8070")

    result = real_client.process_fulltext(pdf_path)

    assert "<TEI" in result.read_text(encoding="utf-8")
