"""Tests para biblioteca.tei_parser."""

from pathlib import Path

import pytest

from biblioteca.tei_parser import (
    GrobidParseError,
    parse_document,
    parse_tei,
    save_plain_text,
)

FIXTURE = Path(__file__).parent / "fixtures" / "grobid_sample.tei.xml"

# Un solo <div> gigante (>20 000 caracteres, muchos párrafos) para activar el
# fallback plano de la decisión P5. Cada párrafo mide ~1000 caracteres para
# que _group_paragraphs produzca varios bloques de ~5000 caracteres.
_PARRAFO_LARGO = (
    "Las palabras se repiten para alcanzar una longitud considerable. " * 15
).strip()
_TEI_DIV_GIGANTE = f"""<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
    <teiHeader>
        <fileDesc>
            <titleStmt><title>Libro con un solo div</title></titleStmt>
        </fileDesc>
    </teiHeader>
    <text>
        <body>
            <div>
                {"".join(f"<p>{_PARRAFO_LARGO} bloque_{i}</p>" for i in range(35))}
            </div>
        </body>
    </text>
</TEI>
"""

TEI_SIN_BODY = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
    <teiHeader>
        <fileDesc>
            <titleStmt><title>Sin body</title></titleStmt>
        </fileDesc>
    </teiHeader>
    <text>
        <back><div type="references"><listBibl/></div></back>
    </text>
</TEI>
"""


def test_devuelve_varias_secciones_sin_texto_vacio() -> None:
    sections = parse_tei(FIXTURE)

    assert len(sections) > 1
    assert all(s.text.strip() for s in sections)


def test_primera_seccion_sin_head_recibe_fallback() -> None:
    sections = parse_tei(FIXTURE)

    assert sections[0].section == "body-1"


def test_existe_seccion_con_head_textual() -> None:
    sections = parse_tei(FIXTURE)
    nombres = {s.section for s in sections}

    assert "II" in nombres
    assert "III El comportamiento vital" in nombres


def test_refs_de_nota_se_eliminan() -> None:
    sections = parse_tei(FIXTURE)
    texto_completo = "\n\n".join(s.text for s in sections)

    assert "foot_1" not in texto_completo


def test_refs_bibliograficas_se_conservan() -> None:
    sections = parse_tei(FIXTURE)
    texto_completo = "\n\n".join(s.text for s in sections)

    assert "(Echeverría, 1998: 161)" in texto_completo


def test_acentos_y_ene_sobreviven_intactos() -> None:
    sections = parse_tei(FIXTURE)
    texto_completo = "\n\n".join(s.text for s in sections)

    assert "Echeverría" in texto_completo
    assert "años" in texto_completo


def test_offsets_char_end_mayor_que_char_start() -> None:
    sections = parse_tei(FIXTURE)

    for s in sections:
        assert s.char_end > s.char_start


def test_tei_sin_body_levanta_grobid_parse_error(tmp_path: Path) -> None:
    tei_path = tmp_path / "sin_body.tei.xml"
    tei_path.write_text(TEI_SIN_BODY, encoding="utf-8")

    with pytest.raises(GrobidParseError):
        parse_tei(tei_path)


def test_tei_ilegible_levanta_grobid_parse_error(tmp_path: Path) -> None:
    tei_path = tmp_path / "roto.tei.xml"
    tei_path.write_text("<TEI><text><body>", encoding="utf-8")

    with pytest.raises(GrobidParseError):
        parse_tei(tei_path)


# --- parse_document: invariante de offsets (criterio 4 del Verificador) ---


def test_invariante_offsets_full_text_fixture_real() -> None:
    """Requisito crítico: para CADA sección, el slice de full_text debe ser exacto."""
    doc = parse_document(FIXTURE)

    assert len(doc.sections) > 0
    for s in doc.sections:
        assert doc.full_text[s.char_start : s.char_end] == s.text


def test_longitud_full_text_coincide_con_secciones_y_separadores() -> None:
    doc = parse_document(FIXTURE)

    suma_secciones = sum(len(s.text) for s in doc.sections)
    separadores = (len(doc.sections) - 1) * len("\n\n")
    assert len(doc.full_text) == suma_secciones + separadores


def test_offsets_estrictamente_crecientes_y_sin_solape() -> None:
    doc = parse_document(FIXTURE)

    for anterior, actual in zip(doc.sections, doc.sections[1:]):
        assert actual.char_start > anterior.char_end
        assert actual.char_start >= anterior.char_end


def test_fixture_real_no_activa_fallback_plano() -> None:
    doc = parse_document(FIXTURE)

    assert doc.used_flat_fallback is False
    assert len(doc.sections) == 8


def test_div_gigante_activa_fallback_plano(tmp_path: Path) -> None:
    tei_path = tmp_path / "libro_div_gigante.tei.xml"
    tei_path.write_text(_TEI_DIV_GIGANTE, encoding="utf-8")

    doc = parse_document(tei_path)

    assert doc.used_flat_fallback is True
    assert len(doc.sections) > 1
    assert all(s.section == "body" for s in doc.sections)
    for s in doc.sections:
        assert doc.full_text[s.char_start : s.char_end] == s.text


# --- save_plain_text ---


def test_save_plain_text_escribe_contenido_identico(tmp_path: Path) -> None:
    doc = parse_document(FIXTURE)
    text_dir = tmp_path / "text"

    out_path = save_plain_text(doc, "doi:10.15174/rv.v0i11.24", text_dir)

    assert out_path.read_text(encoding="utf-8") == doc.full_text
    assert "Echeverría" in out_path.read_text(encoding="utf-8")
    assert "años" in out_path.read_text(encoding="utf-8")


def test_save_plain_text_sanea_paper_id_con_dos_puntos_y_barra(tmp_path: Path) -> None:
    doc = parse_document(FIXTURE)
    text_dir = tmp_path / "text"

    out_path = save_plain_text(doc, "doi:10.15174/rv.v0i11.24", text_dir)

    assert out_path.name == "doi_10.15174_rv.v0i11.24.txt"
    assert out_path.parent == text_dir


def test_save_plain_text_crea_directorio_y_es_idempotente(tmp_path: Path) -> None:
    doc = parse_document(FIXTURE)
    text_dir = tmp_path / "no_existe_aun" / "text"

    out_path_1 = save_plain_text(doc, "doi:10.1/x", text_dir)
    out_path_2 = save_plain_text(doc, "doi:10.1/x", text_dir)

    assert out_path_1 == out_path_2
    assert out_path_2.read_text(encoding="utf-8") == doc.full_text
