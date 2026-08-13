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

from biblioteca.models import ParsedDocument, SectionText

TEI_NS = "http://www.tei-c.org/ns/1.0"
_NSMAP = {"tei": TEI_NS}

_WHITESPACE_RE = re.compile(r"\s+")
_SECTION_SEPARATOR = "\n\n"

# Decisión P5 (docs/03-REGISTRO-CONSIDERACIONES-BIBLIOTECA_v12.md): libros mal
# parseados por GROBID producen 0 o 1 divs útiles pese a tener mucho texto.
_FALLBACK_MIN_CHARS = 20_000
_FALLBACK_BLOCK_SIZE = 5_000


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
    body = _load_body(tei_path)
    divs = body.findall("tei:div", namespaces=_NSMAP)
    named_texts = _named_texts_from_divs(divs)
    _, sections = _assign_offsets(named_texts)
    return sections


def parse_document(tei_path: Path) -> ParsedDocument:
    """Parsea un TEI completo a un `ParsedDocument` con texto e invariante de offsets.

    Reutiliza la extracción por `<div>` de `parse_tei`. Si esa extracción
    produce 0 o 1 secciones útiles y el texto del `<body>` supera los
    `_FALLBACK_MIN_CHARS`, activa el fallback plano de la decisión P5: se
    segmenta por párrafos de todo el `<body>` en bloques de ~`_FALLBACK_BLOCK_SIZE`
    caracteres, todos con `section="body"`, y se marca `used_flat_fallback=True`.
    """
    body = _load_body(tei_path)
    divs = body.findall("tei:div", namespaces=_NSMAP)
    named_texts = _named_texts_from_divs(divs)

    paragraphs = _all_body_paragraphs(body)
    total_len = len(_SECTION_SEPARATOR.join(paragraphs))

    used_flat_fallback = False
    if len(named_texts) <= 1 and total_len > _FALLBACK_MIN_CHARS:
        named_texts = [("body", block) for block in _group_paragraphs(paragraphs)]
        used_flat_fallback = True

    full_text, sections = _assign_offsets(named_texts)
    return ParsedDocument(
        full_text=full_text,
        sections=sections,
        used_flat_fallback=used_flat_fallback,
    )


def save_plain_text(doc: ParsedDocument, paper_id: str, text_dir: Path) -> Path:
    """Guarda `doc.full_text` en UTF-8 en `text_dir/{paper_id_sanitizado}.txt`.

    El saneado de `paper_id` sigue la misma convención que los PDFs del
    excavador: reemplaza `:` y `/` por `_`. Crea `text_dir` si no existe.
    Idempotente: sobrescribe el archivo si ya existía.
    """
    text_dir.mkdir(parents=True, exist_ok=True)
    sanitized_id = paper_id.replace(":", "_").replace("/", "_")
    out_path = text_dir / f"{sanitized_id}.txt"
    out_path.write_text(doc.full_text, encoding="utf-8")
    return out_path


def _load_body(tei_path: Path) -> etree._Element:
    """Parsea el TEI y devuelve el elemento `<body>`, o lanza `GrobidParseError`."""
    try:
        tree = etree.parse(str(tei_path))
    except etree.XMLSyntaxError as exc:
        raise GrobidParseError(f"TEI ilegible en {tei_path}: {exc}") from exc

    root = tree.getroot()
    body_elements = root.findall(".//tei:text/tei:body", namespaces=_NSMAP)
    if not body_elements:
        raise GrobidParseError(f"TEI sin <body> en {tei_path}")
    return body_elements[0]


def _named_texts_from_divs(divs: list[etree._Element]) -> list[tuple[str, str]]:
    """Extrae pares `(section, text)` de los divs hijos directos del body, sin vacíos."""
    named_texts: list[tuple[str, str]] = []
    for n, div in enumerate(divs, start=1):
        section_name = _section_name(div, n)
        text = _extract_div_text(div)
        if text:
            named_texts.append((section_name, text))
    return named_texts


def _assign_offsets(named_texts: list[tuple[str, str]]) -> tuple[str, list[SectionText]]:
    """Construye `full_text` y las `SectionText` calculando los offsets al concatenar.

    Garantiza la invariante `full_text[s.char_start:s.char_end] == s.text` por
    construcción: los offsets se calculan mientras se arma la concatenación,
    nunca a posteriori.
    """
    parts: list[str] = []
    sections: list[SectionText] = []
    offset = 0
    for section_name, text in named_texts:
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
        parts.append(text)
        offset = char_end + len(_SECTION_SEPARATOR)

    full_text = _SECTION_SEPARATOR.join(parts)
    return full_text, sections


def _all_body_paragraphs(body: etree._Element) -> list[str]:
    """Texto normalizado de todos los `<p>` del body (recursivo), sin vacíos."""
    paragraphs: list[str] = []
    for p in body.findall(".//tei:p", namespaces=_NSMAP):
        text = _normalize_whitespace(_paragraph_text(p))
        if text:
            paragraphs.append(text)
    return paragraphs


def _group_paragraphs(paragraphs: list[str], block_size: int = _FALLBACK_BLOCK_SIZE) -> list[str]:
    """Agrupa párrafos en bloques de ~`block_size` caracteres (fallback plano P5)."""
    blocks: list[str] = []
    current: list[str] = []
    current_len = 0
    for paragraph in paragraphs:
        added_len = len(paragraph) + (len(_SECTION_SEPARATOR) if current else 0)
        if current and current_len + added_len > block_size:
            blocks.append(_SECTION_SEPARATOR.join(current))
            current = [paragraph]
            current_len = len(paragraph)
        else:
            current.append(paragraph)
            current_len += added_len
    if current:
        blocks.append(_SECTION_SEPARATOR.join(current))
    return blocks


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
