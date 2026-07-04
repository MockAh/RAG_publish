"""Normalización de RawHit -> PaperRecord (contrato C1) por API de origen.

`normalize_*` mapea el payload crudo de cada API a un `PaperRecord` provisional
(`relevance_score=0.0`, `pdf_path=None`); devuelve None si falta título o año
(el llamador manda esos hits a descartados como `invalid_record`).

`canonical_enrich` completa, sin sobrescribir, los campos vacíos de un record
ya normalizado usando un RawHit de OpenAlex ya obtenido (A2: normalizador
canónico). Es una función pura: la llamada de red la hace la pipeline.
"""

import re
from datetime import datetime, timezone

from excavador.apis.openalex import invert_abstract
from excavador.models import PaperRecord, RawHit, WorkType

_OPENALEX_WORK_TYPE_MAP: dict[str, WorkType] = {
    "article": "article",
    "book": "book",
    "book-chapter": "book-chapter",
    "dissertation": "thesis",
}

_CROSSREF_WORK_TYPE_MAP: dict[str, WorkType] = {
    "journal-article": "article",
    "book": "book",
    "book-chapter": "book-chapter",
    "dissertation": "thesis",
}

_JATS_TAG_RE = re.compile(r"<[^>]+>")


def _paper_id(hit: RawHit) -> str:
    """`"doi:<doi>"` si el hit tiene DOI; si no, `"<source_api>:<external_id>"`."""
    if hit.doi:
        return f"doi:{hit.doi.strip().lower()}"
    return f"{hit.source_api}:{hit.external_id}"


def _short_id(url_or_id: str) -> str:
    return url_or_id.rsplit("/", 1)[-1]


def _openalex_abstract(raw: dict) -> str:
    return invert_abstract(raw.get("abstract_inverted_index"))


def _openalex_venue(raw: dict) -> str | None:
    primary_location = raw.get("primary_location") or {}
    source = primary_location.get("source") or {}
    return source.get("display_name")


def _openalex_references(raw: dict) -> list[str]:
    return [f"openalex:{_short_id(url)}" for url in raw.get("referenced_works") or []]


def _openalex_work_type(raw: dict) -> WorkType:
    return _OPENALEX_WORK_TYPE_MAP.get(raw.get("type"), "other")


def normalize_openalex(hit: RawHit) -> PaperRecord | None:
    """Mapea un RawHit de OpenAlex a PaperRecord. None si falta título o año."""
    raw = hit.raw
    title = raw.get("display_name")
    year = raw.get("publication_year")
    if not title or not year:
        return None

    authors = [
        authorship["author"]["display_name"]
        for authorship in raw.get("authorships") or []
        if authorship.get("author") and authorship["author"].get("display_name")
    ]

    return PaperRecord(
        paper_id=_paper_id(hit),
        doi=hit.doi,
        title=title,
        authors=authors,
        year=year,
        venue=_openalex_venue(raw),
        abstract=_openalex_abstract(raw),
        source_api="openalex",
        work_type=_openalex_work_type(raw),
        pdf_path=None,
        relevance_score=0.0,
        references_ids=_openalex_references(raw),
        ingested_at=datetime.now(timezone.utc),
    )


def normalize_crossref(hit: RawHit) -> PaperRecord | None:
    """Mapea un RawHit de Crossref a PaperRecord. None si falta título o año."""
    raw = hit.raw
    titles = raw.get("title") or []
    title = titles[0] if titles else None

    date_parts = (raw.get("issued") or {}).get("date-parts") or []
    year = date_parts[0][0] if date_parts and date_parts[0] else None

    if not title or not year:
        return None

    authors = [
        f"{author.get('given', '')} {author.get('family', '')}".strip()
        for author in raw.get("author") or []
    ]

    containers = raw.get("container-title") or []
    venue = containers[0] if containers else None

    abstract_raw = raw.get("abstract")
    abstract = _JATS_TAG_RE.sub("", abstract_raw) if abstract_raw else ""

    return PaperRecord(
        paper_id=_paper_id(hit),
        doi=hit.doi,
        title=title,
        authors=authors,
        year=year,
        venue=venue,
        abstract=abstract,
        source_api="crossref",
        work_type=_CROSSREF_WORK_TYPE_MAP.get(raw.get("type"), "other"),
        pdf_path=None,
        relevance_score=0.0,
        references_ids=[],
        ingested_at=datetime.now(timezone.utc),
    )


def _s2_work_type(publication_types: list[str] | None) -> WorkType:
    types = publication_types or []
    if "JournalArticle" in types:
        return "article"
    if "Book" in types:
        return "book"
    if "BookSection" in types:
        return "book-chapter"
    if "Dissertation" in types:
        return "thesis"
    return "other"


def normalize_semanticscholar(hit: RawHit) -> PaperRecord | None:
    """Mapea un RawHit de Semantic Scholar a PaperRecord. None si falta título o año."""
    raw = hit.raw
    title = raw.get("title")
    year = raw.get("year")
    if not title or not year:
        return None

    authors = [
        author["name"] for author in raw.get("authors") or [] if author.get("name")
    ]
    references_ids = [
        f"semanticscholar:{reference['paperId']}"
        for reference in raw.get("references") or []
        if reference.get("paperId")
    ]

    return PaperRecord(
        paper_id=_paper_id(hit),
        doi=hit.doi,
        title=title,
        authors=authors,
        year=year,
        venue=raw.get("venue"),
        abstract=raw.get("abstract") or "",
        source_api="semanticscholar",
        work_type=_s2_work_type(raw.get("publicationTypes")),
        pdf_path=None,
        relevance_score=0.0,
        references_ids=references_ids,
        ingested_at=datetime.now(timezone.utc),
    )


def canonical_enrich(record: PaperRecord, raw_enriched: RawHit | None) -> PaperRecord:
    """Completa SOLO los campos vacíos de `record` con un RawHit de OpenAlex.

    No sobrescribe campos ya presentes. Si `raw_enriched` es None, devuelve
    `record` intacto.
    """
    if raw_enriched is None:
        return record

    raw = raw_enriched.raw
    updates: dict = {}
    if record.abstract == "":
        updates["abstract"] = _openalex_abstract(raw)
    if record.venue is None:
        updates["venue"] = _openalex_venue(raw)
    if not record.references_ids:
        updates["references_ids"] = _openalex_references(raw)
    if record.work_type == "other":
        updates["work_type"] = _openalex_work_type(raw)

    if not updates:
        return record
    return record.model_copy(update=updates)
