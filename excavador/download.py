"""Descarga de PDFs, solo desde URLs de Acceso Abierto (OA).

Nunca construye URLs de editoriales ni resuelve DOIs a ciegas (T10): la URL
candidata sale exclusivamente de los campos OA que ya trae el payload crudo
de OpenAlex o Semantic Scholar.
"""

import logging
from pathlib import Path

import httpx

from excavador.models import PaperRecord

logger = logging.getLogger(__name__)

_PDF_MAGIC = b"%PDF-"


def _oa_pdf_url(raw: dict | None) -> str | None:
    """URL candidata de PDF OA, o None si no hay ninguna.

    Orden de precedencia: `best_oa_location.pdf_url` (OpenAlex),
    `open_access.oa_url` (OpenAlex), `openAccessPdf.url` (Semantic Scholar).
    """
    if raw is None:
        return None

    best_oa_location = raw.get("best_oa_location") or {}
    if best_oa_location.get("pdf_url"):
        return best_oa_location["pdf_url"]

    open_access = raw.get("open_access") or {}
    if open_access.get("oa_url"):
        return open_access["oa_url"]

    open_access_pdf = raw.get("openAccessPdf") or {}
    if open_access_pdf.get("url"):
        return open_access_pdf["url"]

    return None


def _pdf_filename(paper_id: str) -> str:
    return paper_id.replace(":", "_").replace("/", "_") + ".pdf"


def download_pdf(
    record: PaperRecord, raw: dict | None, pdf_dir: Path, client: httpx.Client
) -> str | None:
    """Descarga el PDF OA de `record` si hay una URL candidata.

    Devuelve la ruta local como string, o None si no hay PDF OA, el
    contenido descargado no es un PDF válido, o falla la red. Nunca
    propaga excepciones: un PDF caído no puede tumbar la pipeline.
    """
    url = _oa_pdf_url(raw)
    if url is None:
        return None

    pdf_dir.mkdir(parents=True, exist_ok=True)
    path = pdf_dir / _pdf_filename(record.paper_id)
    if path.exists():
        return str(path)

    try:
        response = client.get(url, timeout=30, follow_redirects=True)
        response.raise_for_status()
        content = response.content
    except httpx.HTTPError:
        logger.warning("Descarga fallida para %s (url=%s)", record.paper_id, url)
        return None

    if content[:5] != _PDF_MAGIC:
        logger.warning(
            "Contenido no-PDF descargado para %s (url=%s)", record.paper_id, url
        )
        return None

    path.write_bytes(content)
    return str(path)
