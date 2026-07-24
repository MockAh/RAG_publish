"""Extracción de secciones de texto a partir de un TEI generado por GROBID.

Solo se procesa el `<body>` del TEI: el `teiHeader` se ignora por completo,
incluso su `<abstract>`, porque en este corpus GROBID a veces mete el resumen
dentro de `<affiliation>/<orgName>` (ver hallazgo A1 en
`docs/03-REGISTRO-CONSIDERACIONES-BIBLIOTECA.md`). El abstract citable se
obtiene de SQLite en M11, nunca de aquí.
"""

from __future__ import annotations

import re
from pathlib import Path

from lxml import etree

from biblioteca.models import SectionText

TEI_NS = "http://www.tei-c.org/ns/1.0"
_NSMAP = {"tei": TEI_NS}

_WHITESPACE_RE = re.compile(r"\s+")


class GrobidParseError(Exception):
    """Error al parsear un TEI: XML ilegible o sin `<body>`."""


def parse_tei(tei_path: Path) -> list[SectionText]:
    """Extrae las secciones del `<body>` de un TEI y devuelve una lista de `SectionText`.

    Cada `<div>` hijo directo del `<body>` produce una `SectionText`. El nombre
    de sección proviene de su `<head>`; si no tiene `<head>` o está vacío, se usa
    el fallback ``f"body-{n}"`` (n = índice del div, empezando en 1). Las
    secciones cuyo texto quede vacío tras la limpieza se descartan. Los
    `char_start`/`char_end` son offsets acumulados sobre la concatenación de
    todas las secciones separadas por ``\\n\\n``.

    Lanza `GrobidParseError` si el XML es ilegible o no contiene `<body>`.
    """
    try:
        tree = etree.parse(str(tei_path))
    except etree.XMLSyntaxError as exc:
        raise GrobidParseError(f"TEI ilegible en {tei_path}: {exc}") from exc

    root = tree.getroot()
    body_elements = root.findall(".//tei:text/tei:body", namespaces=_NSMAP)
    if not body_elements:
        raise GrobidParseError(f"TEI sin <body> en {tei_path}")
    body = body_elements[0]

    divs = body.findall("tei:div", namespaces=_NSMAP)

    sections: list[SectionText] = []
    offset = 0
    for n, div in enumerate(divs, start=1):
        section_name = _section_name(div, n)
        text = _extract_div_text(div)
        if not text:
            continue
        char_start = offset
        char_end = char_start + len(text)
        sections.append(
            SectionText(
                section=section_name,
                text=text,
                char_start=char_start,
                char_end=char_end,
            )
        )
        offset = char_end + 2  # +2 por el separador "\n\n" entre secciones

    return sections


def _section_name(div: etree._Element, n: int) -> str:
    """Nombre de sección: texto del `<head>` del div, o `f"body-{n}"` si falta/vacío."""
    head = div.find("tei:head", namespaces=_NSMAP)
    if head is not None:
        head_text = _normalize_whitespace("".join(head.itertext()))
        if head_text:
            return head_text
    return f"body-{n}"


def _extract_div_text(div: etree._Element) -> str:
    """Concatena los `<p>` de un div (separados por `\\n\\n`) con las reglas de `<ref>`."""
    paragraphs: list[str] = []
    for p in div.findall("tei:p", namespaces=_NSMAP):
        paragraph_text = _normalize_whitespace(_paragraph_text(p))
        if paragraph_text:
            paragraphs.append(paragraph_text)
    return "\n\n".join(paragraphs)


def _paragraph_text(p: etree._Element) -> str:
    """Texto de un `<p>` eliminando `<ref type="foot">` y conservando el resto como texto plano."""
    # Se trabaja sobre una copia para poder eliminar los <ref type="foot"> sin
    # afectar al árbol original.
    p_copy = etree.fromstring(etree.tostring(p))
    for ref in p_copy.findall(".//tei:ref[@type='foot']", namespaces=_NSMAP):
        ref.getparent().remove(ref)
    return "".join(p_copy.itertext())


def _normalize_whitespace(text: str) -> str:
    """Colapsa espacios/saltos múltiples y aplica `strip()`."""
    return _WHITESPACE_RE.sub(" ", text).strip()
