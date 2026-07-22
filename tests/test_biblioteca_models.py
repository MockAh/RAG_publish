"""Tests para biblioteca.models (Chunk, SectionText, IndexStats)."""

import pytest
from pydantic import ValidationError

from biblioteca.models import Chunk, IndexStats, SectionText


def _make_chunk(**overrides: object) -> Chunk:
    """Construye un `Chunk` válido, permitiendo sobreescribir campos puntuales."""
    data: dict[str, object] = {
        "chunk_id": "doi:10.1234/abc#introduction#0",
        "paper_id": "doi:10.1234/abc",
        "section": "introduction",
        "text": "Este es un fragmento de texto de ejemplo.",
        "char_start": 0,
        "char_end": 42,
        "embedding_model": "intfloat/multilingual-e5-large",
    }
    data.update(overrides)
    return Chunk(**data)


def test_chunk_json_round_trip() -> None:
    """Un `Chunk` sobrevive intacto a un round-trip por JSON."""
    chunk = _make_chunk()

    restored = Chunk.model_validate_json(chunk.model_dump_json())

    assert restored == chunk


def test_section_text_json_round_trip() -> None:
    """Un `SectionText` sobrevive intacto a un round-trip por JSON."""
    section = SectionText(
        section="abstract",
        text="Resumen del artículo.",
        char_start=0,
        char_end=22,
    )

    restored = SectionText.model_validate_json(section.model_dump_json())

    assert restored == section


def test_index_stats_json_round_trip() -> None:
    """Un `IndexStats` sobrevive intacto a un round-trip por JSON."""
    stats = IndexStats(
        papers_total=10,
        papers_indexed=8,
        papers_skipped=1,
        papers_failed=1,
        chunks_created=120,
        from_abstract_count=2,
        duration_s=3.75,
    )

    restored = IndexStats.model_validate_json(stats.model_dump_json())

    assert restored == stats


def test_chunk_rechaza_char_end_no_mayor_que_char_start() -> None:
    """`Chunk` rechaza `char_end` <= `char_start`."""
    with pytest.raises(ValidationError):
        _make_chunk(char_start=10, char_end=10)


def test_chunk_rechaza_text_vacio() -> None:
    """`Chunk` rechaza `text` vacío (o solo espacios en blanco)."""
    with pytest.raises(ValidationError):
        _make_chunk(text="   ")


def test_build_id_formato_esperado() -> None:
    """`Chunk.build_id` produce el formato `paper_id#section#seq` de C2."""
    chunk_id = Chunk.build_id("doi:10.1234/abc", "results", 3)

    assert chunk_id == "doi:10.1234/abc#results#3"


def test_chunk_con_acentos_y_ene_sobrevive_round_trip() -> None:
    """Un `Chunk` con acentos y «ñ» en `text` sobrevive el round-trip intacto."""
    texto = "La recepción de Echeverría en América Latina: años de análisis y crítica."
    chunk = _make_chunk(text=texto)

    restored = Chunk.model_validate_json(chunk.model_dump_json())

    assert restored.text == texto
    assert restored == chunk
