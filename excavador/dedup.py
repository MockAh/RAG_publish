"""Deduplicación de PaperRecord (T6).

Clave primaria: DOI normalizado. Sin DOI: (título normalizado, year).

Nota deliberada: un record CON DOI y otro SIN DOI que comparten título+year no
se dedupean entre sí (claves distintas: ("doi", ...) vs ("title", ..., year)).
El enriquecimiento canónico (T5, `canonical_enrich`) minimiza este caso al
completar el DOI vía OpenAlex antes de llegar aquí.
"""

import re
import unicodedata

from excavador.models import PaperRecord

_DOI_PREFIXES = ("https://doi.org/", "http://doi.org/", "doi.org/", "doi:")
_TITLE_ALLOWED_RE = re.compile(r"[^a-z0-9 ]")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_doi(doi: str) -> str:
    """Minúsculas, sin espacios en los extremos, sin prefijos de URL/esquema."""
    normalized = doi.strip().lower()
    for prefix in _DOI_PREFIXES:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    return normalized


def normalize_title(title: str) -> str:
    """Minúsculas, sin acentos/diacríticos, solo [a-z0-9 ], espacios colapsados."""
    decomposed = unicodedata.normalize("NFD", title.lower())
    without_marks = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    only_allowed = _TITLE_ALLOWED_RE.sub("", without_marks)
    return _WHITESPACE_RE.sub(" ", only_allowed).strip()


def _group_key(record: PaperRecord) -> tuple:
    if record.doi:
        return ("doi", normalize_doi(record.doi))
    return ("title", normalize_title(record.title), record.year)


def _completeness(record: PaperRecord) -> int:
    """Cuenta de campos "con contenido" usada para elegir al ganador."""
    return sum(
        (
            record.doi is not None,
            record.venue is not None,
            record.abstract != "",
            bool(record.references_ids),
            record.pdf_path is not None,
        )
    )


def _pick_winner_index(group: list[PaperRecord]) -> int:
    winner_idx = 0
    for i in range(1, len(group)):
        candidate, current_winner = group[i], group[winner_idx]
        candidate_score = _completeness(candidate)
        winner_score = _completeness(current_winner)
        if candidate_score > winner_score:
            winner_idx = i
        elif candidate_score == winner_score:
            if candidate.source_api == "openalex" and current_winner.source_api != "openalex":
                winner_idx = i
            # empate total: gana el primero visto (no se cambia winner_idx)
    return winner_idx


def _merge_references(group: list[PaperRecord]) -> list[str]:
    """Unión de references_ids de todo el grupo, sin duplicados, orden estable."""
    return list(dict.fromkeys(ref for record in group for ref in record.references_ids))


def dedup(records: list[PaperRecord]) -> tuple[list[PaperRecord], list[PaperRecord]]:
    """Deduplica `records`. Devuelve (únicos, duplicados).

    El orden relativo de los únicos es estable (orden de primera aparición).
    """
    groups: dict[tuple, list[PaperRecord]] = {}
    key_order: list[tuple] = []
    for record in records:
        key = _group_key(record)
        if key not in groups:
            groups[key] = []
            key_order.append(key)
        groups[key].append(record)

    uniques: list[PaperRecord] = []
    duplicates: list[PaperRecord] = []

    for key in key_order:
        group = groups[key]
        if len(group) == 1:
            uniques.append(group[0])
            continue

        winner_idx = _pick_winner_index(group)
        winner = group[winner_idx].model_copy(
            update={"references_ids": _merge_references(group)}
        )
        uniques.append(winner)
        duplicates.extend(record for idx, record in enumerate(group) if idx != winner_idx)

    return uniques, duplicates
