"""Tests para biblioteca.tei_parser."""

from pathlib import Path

import pytest

from biblioteca.tei_parser import GrobidParseError, parse_tei

FIXTURE = Path(__file__).parent / "fixtures" / "grobid_sample.tei.xml"

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
