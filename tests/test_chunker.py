"""Tests para biblioteca.chunker."""

import unicodedata
from pathlib import Path

import pytest

from biblioteca.chunker import chunk_sections, count_tokens, split_sentences
from biblioteca.models import SectionText
from biblioteca.tei_parser import parse_document

FIXTURE = Path(__file__).parent / "fixtures" / "grobid_sample.tei.xml"


def _word_counter(text: str) -> int:
    """Tokenizer falso para tests rápidos: un token por palabra."""
    return len(text.split())


def _normalize(name: str) -> str:
    """Normalización de nombres de sección igual a la de `biblioteca.chunker`."""
    decomposed = unicodedata.normalize("NFD", name.lower())
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn").strip()


def _abs_sentence_spans(section: SectionText) -> list[tuple[int, int]]:
    """Spans de oraciones de `section.text` trasladados a offsets absolutos."""
    return [(section.char_start + s, section.char_start + e) for s, e in split_sentences(section.text)]


# --- split_sentences -------------------------------------------------------


def test_split_sentences_texto_vacio() -> None:
    assert split_sentences("") == []


def test_split_sentences_no_corta_en_p_ej() -> None:
    text = "Hay varios casos, p. ej. Este no debe partirse. Aquí sí termina la oración."
    spans = split_sentences(text)

    assert len(spans) == 2
    assert text[spans[0][0] : spans[0][1]].strip() == (
        "Hay varios casos, p. ej. Este no debe partirse."
    )


def test_split_sentences_no_corta_en_etc() -> None:
    text = "Se usan diagramas, mapas, etc. Estos ejemplos abundan en el texto."
    spans = split_sentences(text)

    assert len(spans) == 1


def test_split_sentences_no_corta_dentro_de_parentesis_de_cita() -> None:
    text = "Esto se sostiene (Echeverría, 1998: 161). Sin embargo, hay matices."
    spans = split_sentences(text)

    assert len(spans) == 2
    assert text[spans[0][0] : spans[0][1]].strip() == "Esto se sostiene (Echeverría, 1998: 161)."


def test_split_sentences_no_corta_dentro_de_parentesis_aunque_parezca_limite() -> None:
    text = "El argumento continúa (Ver Nota Final. Página 10) sin interrupciones reales."
    spans = split_sentences(text)

    assert len(spans) == 1


def test_split_sentences_protege_iniciales_de_nombre() -> None:
    text = "El autor J. Pérez lo explica así. Esta es otra oración distinta."
    spans = split_sentences(text)

    assert len(spans) == 2


def test_split_sentences_spans_no_se_solapan_y_reconstruyen_texto() -> None:
    text = (
        "Primera oración. Segunda oración con matices (Autor, 2020: 5). "
        "Tercera y última oración, p. ej. con casos y etc. finales."
    )
    spans = split_sentences(text)

    assert spans
    for (_, end1), (start2, _) in zip(spans, spans[1:]):
        assert end1 == start2
    assert spans[0][0] == 0
    assert spans[-1][1] == len(text)
    assert "".join(text[s:e] for s, e in spans) == text


# --- count_tokens -----------------------------------------------------------


def test_count_tokens_usa_counter_inyectado() -> None:
    assert count_tokens("hola mundo esto es una prueba", counter=_word_counter) == 6


# --- chunk_sections (fixture real) ------------------------------------------


def test_chunks_son_rebanadas_literales_de_full_text() -> None:
    doc = parse_document(FIXTURE)
    chunks = chunk_sections(doc.sections, doc.full_text, "paper1", "e5-model", counter=_word_counter)

    assert chunks
    for chunk in chunks:
        assert doc.full_text[chunk.char_start : chunk.char_end] == chunk.text


def test_ningun_chunk_cruza_secciones() -> None:
    doc = parse_document(FIXTURE)
    chunks = chunk_sections(doc.sections, doc.full_text, "paper1", "e5-model", counter=_word_counter)
    sections_by_name = {s.section: s for s in doc.sections}

    for chunk in chunks:
        section = sections_by_name[chunk.section]
        assert chunk.char_start >= section.char_start
        assert chunk.char_end <= section.char_end


def test_ninguna_oracion_queda_partida() -> None:
    doc = parse_document(FIXTURE)
    chunks = chunk_sections(doc.sections, doc.full_text, "paper1", "e5-model", counter=_word_counter)

    for section in doc.sections:
        abs_spans = _abs_sentence_spans(section)
        starts = {s for s, _ in abs_spans}
        ends = {e for _, e in abs_spans}
        for chunk in chunks:
            if chunk.section == section.section:
                assert chunk.char_start in starts
                assert chunk.char_end in ends


def test_chunks_respetan_max_tokens_salvo_oracion_unica_sobredimensionada() -> None:
    doc = parse_document(FIXTURE)
    sections_by_name = {s.section: s for s in doc.sections}
    chunks = chunk_sections(
        doc.sections, doc.full_text, "paper1", "e5-model", max_tokens=500, counter=_word_counter
    )

    for chunk in chunks:
        tokens = count_tokens(chunk.text, counter=_word_counter)
        if tokens > 500:
            section = sections_by_name[chunk.section]
            abs_spans = _abs_sentence_spans(section)
            contained = [
                span for span in abs_spans if span[0] >= chunk.char_start and span[1] <= chunk.char_end
            ]
            assert contained == [(chunk.char_start, chunk.char_end)]


def test_p7_descarta_bibliografia() -> None:
    doc = parse_document(FIXTURE)
    assert any(_normalize(s.section) == "bibliografia" for s in doc.sections)

    chunks = chunk_sections(doc.sections, doc.full_text, "paper1", "e5-model", counter=_word_counter)

    assert all(_normalize(c.section) != "bibliografia" for c in chunks)


def test_chunk_ids_unicos() -> None:
    doc = parse_document(FIXTURE)
    chunks = chunk_sections(doc.sections, doc.full_text, "paper1", "e5-model", counter=_word_counter)

    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))


def test_chunk_ids_unicos_con_secciones_de_nombre_repetido() -> None:
    text_a = "Primera oración de la sección A. Segunda oración de la sección A. "
    text_b = "Primera oración de la sección B. Segunda oración de la sección B. "
    full_text = text_a + text_b
    sections = [
        SectionText(section="body", text=text_a, char_start=0, char_end=len(text_a)),
        SectionText(section="body", text=text_b, char_start=len(text_a), char_end=len(full_text)),
    ]

    chunks = chunk_sections(sections, full_text, "paper1", "e5-model", counter=_word_counter)

    assert all(c.section == "body" for c in chunks)
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))
    for chunk in chunks:
        assert full_text[chunk.char_start : chunk.char_end] == chunk.text


@pytest.mark.slow
def test_chunks_respetan_max_tokens_con_tokenizer_real() -> None:
    doc = parse_document(FIXTURE)
    chunks = chunk_sections(doc.sections, doc.full_text, "paper1", "intfloat/multilingual-e5-large", max_tokens=500)

    for chunk in chunks:
        tokens = count_tokens(chunk.text)
        assert tokens <= 500 or len(split_sentences(chunk.text)) == 1
