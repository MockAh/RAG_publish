"""Tests para biblioteca.abstract_chunker."""

from datetime import datetime, timezone

from biblioteca.abstract_chunker import chunk_from_abstract, plain_text_for_abstract
from excavador.models import PaperRecord


def _word_counter(text: str) -> int:
    """Tokenizer falso para tests rápidos: un token por palabra."""
    return len(text.split())


def _record(**overrides: object) -> PaperRecord:
    """Construye un `PaperRecord` sintético con valores por defecto razonables."""
    base = dict(
        paper_id="doi:10.1234/abc",
        doi="10.1234/abc",
        title="La definición de la cultura",
        authors=["Bolívar Echeverría"],
        year=1998,
        venue="Itaca",
        abstract="Un análisis sobre la noción de cultura y modernidad barroca en América Latina.",
        source_api="openalex",
        work_type="book",
        pdf_path=None,
        relevance_score=0.87,
        references_ids=[],
        ingested_at=datetime(2026, 7, 4, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return PaperRecord(**base)


def test_abstract_normal_produce_un_solo_chunk() -> None:
    record = _record()

    chunks = chunk_from_abstract(record, embedding_model="e5-test", counter=_word_counter)

    assert len(chunks) == 1
    chunk = chunks[0]
    texto = plain_text_for_abstract(record)
    assert chunk.section == "abstract"
    assert chunk.chunk_id == f"{record.paper_id}#abstract#0"
    assert chunk.char_start == 0
    assert chunk.char_end == len(texto)
    assert chunk.text == texto


def test_chunk_texto_empieza_con_el_titulo() -> None:
    record = _record()

    chunks = chunk_from_abstract(record, embedding_model="e5-test", counter=_word_counter)

    assert chunks[0].text.startswith(record.title)


def test_abstract_vacio_devuelve_lista_vacia() -> None:
    record = _record(abstract="")

    chunks = chunk_from_abstract(record, embedding_model="e5-test", counter=_word_counter)

    assert chunks == []


def test_abstract_solo_espacios_devuelve_lista_vacia() -> None:
    record = _record(abstract="   \n\t  ")

    chunks = chunk_from_abstract(record, embedding_model="e5-test", counter=_word_counter)

    assert chunks == []


def test_abstract_muy_largo_produce_varios_chunks_validos() -> None:
    abstract_largo = " ".join(f"Palabra{i} de un análisis extenso." for i in range(400))
    record = _record(abstract=abstract_largo)

    chunks = chunk_from_abstract(
        record, embedding_model="e5-test", max_tokens=50, counter=_word_counter
    )
    texto = plain_text_for_abstract(record)

    assert len(chunks) > 1
    assert {c.section for c in chunks} == {"abstract"}
    assert len({c.chunk_id for c in chunks}) == len(chunks)
    for chunk in chunks:
        assert texto[chunk.char_start : chunk.char_end] == chunk.text


def test_diacriticos_degradados_sobreviven_intactos() -> None:
    record = _record(
        title="Ensayo sobre Bolvar Echeverra y la modernidad",
        abstract="La nocin de cultura y la razn moderna en Amrica Latina.",
    )

    chunks = chunk_from_abstract(record, embedding_model="e5-test", counter=_word_counter)

    assert len(chunks) == 1
    assert chunks[0].text == plain_text_for_abstract(record)
    assert "Bolvar Echeverra" in chunks[0].text


def test_embedding_model_se_copia_tal_cual() -> None:
    abstract_largo = " ".join(f"Palabra{i} de un análisis extenso." for i in range(400))
    record = _record(abstract=abstract_largo)

    chunks = chunk_from_abstract(
        record, embedding_model="intfloat/multilingual-e5-large", max_tokens=50, counter=_word_counter
    )

    assert len(chunks) > 1
    assert all(c.embedding_model == "intfloat/multilingual-e5-large" for c in chunks)


def test_plain_text_for_abstract_coincide_con_texto_de_offsets() -> None:
    record = _record()

    texto = plain_text_for_abstract(record)
    chunks = chunk_from_abstract(record, embedding_model="e5-test", counter=_word_counter)

    assert texto == f"{record.title}. {record.abstract}"
    assert chunks[0].text == texto
