"""Modelos de datos del Excavador.

`PaperRecord` es el contrato C1 (ver `docs/01-CONTRATOS-DE-DATOS_v11.md`):
esquema compartido con el Procesador. NO añadir, eliminar ni renombrar campos.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

SourceApi = Literal["arxiv", "openalex", "semanticscholar", "crossref", "pubmed"]
WorkType = Literal["article", "book", "book-chapter", "thesis", "other"]


class PaperRecord(BaseModel):
    """C1 · salida del Excavador, entrada del Procesador."""

    paper_id: str  # interno, estable: "doi:<doi normalizado>" o "<source_api>:<id nativo>"
    doi: str | None
    title: str
    authors: list[str]
    year: int
    venue: str | None
    abstract: str
    source_api: SourceApi
    work_type: WorkType
    pdf_path: str | None  # ruta local; None si no se obtuvo PDF
    relevance_score: float = Field(ge=0, le=1)
    references_ids: list[str]
    ingested_at: datetime


class RawHit(BaseModel):
    """Resultado crudo de cualquier API antes de normalizar."""

    source_api: SourceApi
    raw: dict
    doi: str | None
    title: str | None
    external_id: str  # id nativo de la API


class DiscardedRecord(PaperRecord):
    """Espejo de `PaperRecord` para registros descartados, con su motivo."""

    discard_reason: Literal["low_relevance", "duplicate", "invalid_record"]
