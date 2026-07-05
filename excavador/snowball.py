"""Snowballing bidireccional (A4): referencias (atrás) + citantes (adelante).

Toma los `k` seeds resolubles a id de OpenAlex con mayor `relevance_score` y
expande el corpus en ambas direcciones. Devuelve `RawHit` sin filtrar ni
deduplicar contra la base de datos (eso lo hace la pipeline), pero sí
deduplicados entre sí por `external_id`.
"""

import logging

from excavador.apis.openalex import OpenAlexClient
from excavador.models import PaperRecord, RawHit

logger = logging.getLogger(__name__)


def _resolve_openalex_id(seed: PaperRecord, openalex: OpenAlexClient) -> str | None:
    """Devuelve el id de OpenAlex de `seed`, o None si no es resoluble."""
    if seed.paper_id.startswith("openalex:"):
        return seed.paper_id.removeprefix("openalex:")
    if seed.doi:
        enriched = openalex.enrich(seed.doi)
        if enriched is not None:
            return enriched.external_id
    return None


def _resolve_seeds(
    seeds: list[PaperRecord], openalex: OpenAlexClient, k: int
) -> list[str]:
    """Ids de OpenAlex de los primeros `k` seeds resolubles, por score descendente."""
    ordered = sorted(seeds, key=lambda s: s.relevance_score, reverse=True)
    resolved_ids: list[str] = []
    for seed in ordered:
        if len(resolved_ids) >= k:
            break
        openalex_id = _resolve_openalex_id(seed, openalex)
        if openalex_id is not None:
            resolved_ids.append(openalex_id)
    return resolved_ids


def snowball(seeds: list[PaperRecord], openalex: OpenAlexClient, k: int) -> list[RawHit]:
    """Expande `seeds` bidireccionalmente vía OpenAlex (A4)."""
    resolved_ids = _resolve_seeds(seeds, openalex, k)

    referenced_ids: list[str] = []
    seen_referenced: set[str] = set()
    for openalex_id in resolved_ids:
        for ref_id in openalex.get_references(openalex_id):
            if ref_id not in seen_referenced:
                seen_referenced.add(ref_id)
                referenced_ids.append(ref_id)

    backward_hits = openalex.enrich_batch(referenced_ids) if referenced_ids else []

    forward_hits: list[RawHit] = []
    for openalex_id in resolved_ids:
        forward_hits.extend(openalex.get_citing(openalex_id, max_results=100))

    resolved_ids_set = set(resolved_ids)
    hits: list[RawHit] = []
    seen_external_ids: set[str] = set()
    for hit in [*backward_hits, *forward_hits]:
        if hit.external_id in resolved_ids_set:
            continue
        if hit.external_id in seen_external_ids:
            continue
        seen_external_ids.add(hit.external_id)
        hits.append(hit)

    logger.info(
        "snowball: %d/%d seeds resueltos, %d hits hacia atrás, %d hacia adelante, "
        "%d tras dedup",
        len(resolved_ids),
        k,
        len(backward_hits),
        len(forward_hits),
        len(hits),
    )

    return hits
