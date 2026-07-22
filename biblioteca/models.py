"""Modelos de datos de la Biblioteca.

`Chunk` es el contrato C2 (ver `docs/01-CONTRATOS-DE-DATOS_v11.md`): esquema
compartido con las fases 04 y 05. NO añadir, eliminar ni renombrar campos.
"""

from __future__ import annotations

from pydantic import BaseModel, model_validator


class Chunk(BaseModel):
    """C2 · salida del Indexador, unidad citable de la Biblioteca."""

    chunk_id: str  # f"{paper_id}#{section}#{seq}"
    paper_id: str
    section: str  # "abstract" | "introduction" | "methods" | "results" | ...
    text: str  # 200-500 tokens aprox., sin partir oraciones
    char_start: int  # offsets sobre el texto extraído del paper
    char_end: int
    embedding_model: str  # nombre+versión exactos del modelo usado

    @model_validator(mode="after")
    def _validar_offsets_y_texto(self) -> "Chunk":
        """Verifica que `char_end` > `char_start` y que `text` no esté vacío."""
        if self.char_end <= self.char_start:
            raise ValueError("char_end debe ser mayor que char_start")
        if not self.text.strip():
            raise ValueError("text no puede estar vacío")
        return self

    @classmethod
    def build_id(cls, paper_id: str, section: str, seq: int) -> str:
        """Construye un `chunk_id` con el formato de C2: `paper_id#section#seq`."""
        return f"{paper_id}#{section}#{seq}"


class SectionText(BaseModel):
    """Sección extraída del TEI antes de trocear (modelo interno, no es contrato)."""

    section: str
    text: str
    char_start: int
    char_end: int


class IndexStats(BaseModel):
    """Resultado de una corrida de indexación."""

    papers_total: int
    papers_indexed: int
    papers_skipped: int
    papers_failed: int
    chunks_created: int
    from_abstract_count: int
    duration_s: float
