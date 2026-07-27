"""Troceo de secciones en `Chunk`s citables (contrato C2).

Aplica la decisión P3 (`docs/03-REGISTRO-CONSIDERACIONES-BIBLIOTECA_v13.md`):
chunks sin overlap, delimitados por oraciones completas y sin cruzar
secciones. Aplica también P7: descarta secciones no citables (bibliografía,
notas, etc.) antes de trocear (ver hallazgo A8). El fallback plano P5 puede
producir varias secciones llamadas ``"body"`` (ver A7); el `seq` del
`chunk_id` es un contador global del documento, no por sección, para
garantizar unicidad en ese caso.

La invariante `full_text[chunk.char_start:chunk.char_end] == chunk.text` se
cumple por construcción: los chunks se arman rebanando `full_text` con los
spans de sus oraciones (inicio de la primera, fin de la última), nunca
concatenando cadenas.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Callable

from biblioteca.models import Chunk, SectionText

logger = logging.getLogger(__name__)

_EMBEDDING_MODEL_NAME = "intfloat/multilingual-e5-large"
_tokenizer_cache = None  # cacheado en módulo, cargado lazy en _get_tokenizer

# Secciones no citables (P7, docs/03-REGISTRO-CONSIDERACIONES-BIBLIOTECA_v13.md).
_EXCLUDED_SECTIONS = frozenset(
    {"bibliografia", "referencias", "bibliography", "references", "notas", "obras citadas"}
)

# Abreviaturas comunes del español académico que no terminan una oración.
_PROTECTED_ABBREVIATIONS = frozenset(
    {"p", "ej", "etc", "cf", "vol", "pp", "ed", "núm", "fig", "dr", "sr", "sra", "op", "cit", "ibid"}
)

_WORD_BEFORE_RE = re.compile(r"([^\W\d_]+)$")
_SENTENCE_END_RE = re.compile(r"[.?!]+[)\"'”’]*(?=\s+[A-ZÁÉÍÓÚÑÜ\"'«¿¡(])")


def split_sentences(text: str) -> list[tuple[int, int]]:
    """Divide `text` en spans (inicio, fin) de oraciones, sin devolver las cadenas.

    Corta en `.`, `?`, `!` seguidos de espacio y mayúscula/comilla/apertura,
    protegiendo abreviaturas comunes (`p. ej.`, `etc.`, `cf.`, `vol.`, `pp.`,
    `ed.`, `núm.`, `fig.`, `Dr.`, `Sr.`, `Sra.`, `op. cit.`, `ibid.`) e
    iniciales de nombre (una mayúscula seguida de punto). No corta dentro de
    paréntesis de cita como `(Echeverría, 1998: 161)`. Los spans devueltos son
    contiguos y cubren todo `text` sin solaparse.
    """
    if not text:
        return []

    depth_at = _paren_depth_at(text)
    boundaries: list[int] = []
    for match in _SENTENCE_END_RE.finditer(text):
        start = match.start()
        if depth_at[start] > 0:
            continue
        if _is_protected_abbreviation(text, start):
            continue
        boundaries.append(match.end())

    split_points = [0, *boundaries, len(text)]
    spans: list[tuple[int, int]] = []
    prev = split_points[0]
    for point in split_points[1:]:
        if point > prev:
            spans.append((prev, point))
            prev = point
    return spans


def _paren_depth_at(text: str) -> list[int]:
    """Profundidad de paréntesis sin cerrar justo antes de cada índice de `text`."""
    depth_at = [0] * (len(text) + 1)
    depth = 0
    for i, ch in enumerate(text):
        depth_at[i] = depth
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(depth - 1, 0)
    depth_at[len(text)] = depth
    return depth_at


def _is_protected_abbreviation(text: str, period_index: int) -> bool:
    """True si la palabra justo antes de `period_index` es abreviatura o inicial protegida."""
    word_match = _WORD_BEFORE_RE.search(text[:period_index])
    if word_match is None:
        return False
    word = word_match.group(1)
    if len(word) == 1 and word.isupper():
        return True
    return word.lower() in _PROTECTED_ABBREVIATIONS


def _get_tokenizer():
    """Carga (lazy) y cachea en módulo el tokenizer real de `_EMBEDDING_MODEL_NAME`."""
    global _tokenizer_cache
    if _tokenizer_cache is None:
        from transformers import AutoTokenizer

        _tokenizer_cache = AutoTokenizer.from_pretrained(_EMBEDDING_MODEL_NAME)
    return _tokenizer_cache


def count_tokens(text: str, counter: Callable[[str], int] | None = None) -> int:
    """Cuenta tokens de `text` con el tokenizer real de e5, o con `counter` si se inyecta."""
    if counter is not None:
        return counter(text)
    tokenizer = _get_tokenizer()
    return len(tokenizer.encode(text, add_special_tokens=False))


def _normalize_section_name(name: str) -> str:
    """Normaliza un nombre de sección: minúsculas, sin acentos (NFD), sin espacios extremos."""
    decomposed = unicodedata.normalize("NFD", name.lower())
    without_accents = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return without_accents.strip()


def _build_chunk(
    paper_id: str,
    section_name: str,
    seq: int,
    start: int,
    end: int,
    full_text: str,
    embedding_model: str,
) -> Chunk:
    """Construye un `Chunk` rebanando `full_text[start:end]` (nunca concatenando)."""
    return Chunk(
        chunk_id=Chunk.build_id(paper_id, section_name, seq),
        paper_id=paper_id,
        section=section_name,
        text=full_text[start:end],
        char_start=start,
        char_end=end,
        embedding_model=embedding_model,
    )


def chunk_sections(
    sections: list[SectionText],
    full_text: str,
    paper_id: str,
    embedding_model: str,
    min_tokens: int = 200,
    max_tokens: int = 500,
    tail_min_tokens: int = 100,
    counter: Callable[[str], int] | None = None,
) -> list[Chunk]:
    """Trocea `sections` en `Chunk`s citables, sin cruzar secciones ni partir oraciones.

    Descarta secciones no citables (P7). Acumula oraciones hasta superar
    `min_tokens` y cierra el chunk antes de rebasar `max_tokens`; el último
    chunk de una sección puede quedar por debajo de `min_tokens`. Si una sola
    oración excede `max_tokens`, se emite como chunk propio (con warning) en
    vez de partirla.

    Tras trocear una sección, si su último chunk queda por debajo de
    `tail_min_tokens` y existe un chunk anterior en esa misma sección, ambos
    se fusionan en uno solo (rebanando `full_text[previo.char_start:cola.char_end]`,
    nunca concatenando), siempre que la suma no rebase `max_tokens`; si la
    rebasaría, la cola se conserva como chunk propio. `seq` es un contador
    global del documento (no se reinicia por sección ni se ve afectado por las
    fusiones: se renumera al final para quedar consecutivo y sin huecos), para
    que `chunk_id` sea único incluso con secciones homónimas (fallback plano
    P5, todas llamadas "body").
    """
    chunks: list[Chunk] = []
    seq = 0

    for section in sections:
        normalized = _normalize_section_name(section.section)
        if normalized in _EXCLUDED_SECTIONS:
            logger.info(
                "Sección '%s' descartada por P7 (stoplist no-citable) en paper %s",
                section.section,
                paper_id,
            )
            continue

        section_start_idx = len(chunks)
        sentence_spans = split_sentences(section.text)
        abs_spans = [(section.char_start + s, section.char_start + e) for s, e in sentence_spans]

        current_start: int | None = None
        current_end: int | None = None

        for sent_start, sent_end in abs_spans:
            sentence_tokens = count_tokens(full_text[sent_start:sent_end], counter)

            if current_start is None:
                if sentence_tokens > max_tokens:
                    logger.warning(
                        "Oración de %d tokens excede max_tokens=%d en sección '%s' de %s; "
                        "se emite como chunk propio sin partirla",
                        sentence_tokens,
                        max_tokens,
                        section.section,
                        paper_id,
                    )
                    chunks.append(
                        _build_chunk(
                            paper_id, section.section, seq, sent_start, sent_end, full_text, embedding_model
                        )
                    )
                    seq += 1
                else:
                    current_start, current_end = sent_start, sent_end
                continue

            prospective_tokens = count_tokens(full_text[current_start:sent_end], counter)
            if prospective_tokens > max_tokens:
                chunks.append(
                    _build_chunk(
                        paper_id, section.section, seq, current_start, current_end, full_text, embedding_model
                    )
                )
                seq += 1
                if sentence_tokens > max_tokens:
                    logger.warning(
                        "Oración de %d tokens excede max_tokens=%d en sección '%s' de %s; "
                        "se emite como chunk propio sin partirla",
                        sentence_tokens,
                        max_tokens,
                        section.section,
                        paper_id,
                    )
                    chunks.append(
                        _build_chunk(
                            paper_id, section.section, seq, sent_start, sent_end, full_text, embedding_model
                        )
                    )
                    seq += 1
                    current_start, current_end = None, None
                else:
                    current_start, current_end = sent_start, sent_end
                continue

            current_end = sent_end
            if prospective_tokens > min_tokens:
                chunks.append(
                    _build_chunk(
                        paper_id, section.section, seq, current_start, current_end, full_text, embedding_model
                    )
                )
                seq += 1
                current_start, current_end = None, None

        if current_start is not None:
            chunks.append(
                _build_chunk(
                    paper_id, section.section, seq, current_start, current_end, full_text, embedding_model
                )
            )
            seq += 1

        if len(chunks) - section_start_idx >= 2:
            tail_chunk = chunks[-1]
            prev_chunk = chunks[-2]
            if count_tokens(tail_chunk.text, counter) < tail_min_tokens:
                merged_tokens = count_tokens(
                    full_text[prev_chunk.char_start : tail_chunk.char_end], counter
                )
                if merged_tokens <= max_tokens:
                    chunks[-2:] = [
                        _build_chunk(
                            paper_id,
                            section.section,
                            0,
                            prev_chunk.char_start,
                            tail_chunk.char_end,
                            full_text,
                            embedding_model,
                        )
                    ]

    for i, chunk in enumerate(chunks):
        expected_id = Chunk.build_id(paper_id, chunk.section, i)
        if chunk.chunk_id != expected_id:
            chunks[i] = chunk.model_copy(update={"chunk_id": expected_id})

    return chunks
