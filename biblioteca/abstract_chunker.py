"""Troceo de título+abstract en `Chunk`s citables (C2) para papers sin PDF.

Aplica P6/E1 (`docs/03-REGISTRO-CONSIDERACIONES-BIBLIOTECA_v15.md`): el texto
de un abstract puede venir tipográficamente degradado (herencia de A1 de fase
02, p. ej. diacríticos rotos); quien indexa estos chunks marca
`from_abstract=True` en el payload de Chroma (P6 no toca C2, así que `Chunk`
no lleva ese campo). Un paper sin PDF y sin abstract no tiene nada citable:
no es un error, se refleja en `IndexStats.papers_skipped`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from biblioteca.chunker import chunk_sections, count_tokens
from biblioteca.models import Chunk, SectionText
from excavador.models import PaperRecord

logger = logging.getLogger(__name__)


def plain_text_for_abstract(record: PaperRecord) -> str:
    """Texto base (título + abstract) sobre el que se calculan los offsets de C2."""
    return f"{record.title}. {record.abstract}"


def chunk_from_abstract(
    record: PaperRecord,
    embedding_model: str,
    max_tokens: int = 500,
    counter: Callable[[str], int] | None = None,
) -> list[Chunk]:
    """Trocea título+abstract de `record` en `Chunk`s citables para papers sin PDF.

    Devuelve lista vacía (con warning, sin excepción) si `record.abstract`
    está vacío o solo tiene espacios. En el caso normal produce un único
    chunk `section="abstract"` cubriendo todo el texto; si el texto supera
    `max_tokens` lo trocea reutilizando `chunk_sections` (misma lógica que el
    cuerpo del paper, sin duplicarla).
    """
    if not record.abstract.strip():
        logger.warning(
            "Paper %s sin PDF y sin abstract: nada citable, se omite", record.paper_id
        )
        return []

    text = plain_text_for_abstract(record)

    if count_tokens(text, counter) <= max_tokens:
        return [
            Chunk(
                chunk_id=Chunk.build_id(record.paper_id, "abstract", 0),
                paper_id=record.paper_id,
                section="abstract",
                text=text,
                char_start=0,
                char_end=len(text),
                embedding_model=embedding_model,
            )
        ]

    section = SectionText(section="abstract", text=text, char_start=0, char_end=len(text))
    return chunk_sections(
        sections=[section],
        full_text=text,
        paper_id=record.paper_id,
        embedding_model=embedding_model,
        max_tokens=max_tokens,
        counter=counter,
    )
