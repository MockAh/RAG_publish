"""Cliente para el servicio GROBID de extracción de TEI a partir de PDFs.

Convierte cada PDF en un XML TEI mediante `POST /api/processFulltextDocument`.
El resultado se cachea en disco (`tei_dir`): si el TEI ya existe, no se vuelve
a llamar a GROBID salvo que se pida explícitamente con `force=True`.
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


class GrobidError(Exception):
    """Error al procesar un PDF con GROBID (status inesperado o cuerpo no-TEI)."""


class GrobidClient:
    """Cliente HTTP para un servicio GROBID."""

    def __init__(self, base_url: str, tei_dir: Path, timeout_s: float = 300.0) -> None:
        """Inicializa el cliente con la URL base de GROBID y el directorio de salida."""
        self.base_url = base_url.rstrip("/")
        self.tei_dir = tei_dir
        self.timeout_s = timeout_s

    def is_alive(self) -> bool:
        """Comprueba si el servicio GROBID responde.

        Devuelve True si `GET {base_url}/api/isalive` responde 200 con "true"
        en el cuerpo. Nunca lanza excepción: cualquier error de red o
        respuesta inesperada se traduce en False.
        """
        try:
            response = httpx.get(f"{self.base_url}/api/isalive", timeout=self.timeout_s)
        except httpx.HTTPError:
            return False
        return response.status_code == 200 and "true" in response.text.lower()

    def tei_path(self, pdf_path: Path) -> Path:
        """Ruta del TEI correspondiente a `pdf_path` dentro de `tei_dir`."""
        return self.tei_dir / (pdf_path.stem + ".tei.xml")

    def process_fulltext(self, pdf_path: Path, force: bool = False) -> Path:
        """Procesa `pdf_path` con GROBID y devuelve la ruta del TEI resultante.

        Si el TEI ya existe en caché y `force` es False, se devuelve esa ruta
        sin llamar a GROBID. En caso contrario, se envía el PDF a
        `processFulltextDocument`, se valida que la respuesta sea XML/TEI
        válido y se escribe en `tei_dir`.
        """
        output_path = self.tei_path(pdf_path)
        if output_path.exists() and not force:
            logger.info("TEI en caché para %s, se omite GROBID", pdf_path.name)
            return output_path

        with pdf_path.open("rb") as pdf_file:
            try:
                response = httpx.post(
                    f"{self.base_url}/api/processFulltextDocument",
                    files={"input": pdf_file},
                    timeout=self.timeout_s,
                )
            except httpx.HTTPError as exc:
                logger.error("Fallo de red al procesar %s con GROBID", pdf_path.name)
                raise GrobidError(f"Fallo de red al procesar {pdf_path.name}: {exc}") from exc

        body = response.text
        if response.status_code != 200 or not (body.startswith("<?xml") or "<TEI" in body):
            logger.error(
                "GROBID devolvió una respuesta inválida para %s (status=%d)",
                pdf_path.name,
                response.status_code,
            )
            raise GrobidError(
                f"Respuesta inválida de GROBID para {pdf_path.name}: "
                f"status={response.status_code}, body={body[:200]!r}"
            )

        self.tei_dir.mkdir(parents=True, exist_ok=True)
        output_path.write_text(body, encoding="utf-8")
        logger.info("TEI generado para %s", pdf_path.name)
        return output_path
