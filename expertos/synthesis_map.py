"""Mapa de Síntesis (C4): lo único que lee el Orquestador para rutear (N11, criterio 5).

No llama al LLM: arma el mapa con lo que ya existe y exige que las fuentes coincidan.

- `topic_label` y `n_papers` salen de la síntesis (C3).
- `one_liner` y `keywords` salen de las etiquetas de producción (A13).
- La partición (`load_corpus_assignment`, con la stoplist E4 ya aplicada) es la referencia.

Una incoherencia es un error, no se repara: indicaría una síntesis o una etiqueta de otra
corrida, y el Orquestador rutearía con un mapa falso sin que nada lo avisara.
"""

import math
from collections.abc import Mapping
from datetime import datetime, timezone

from expertos.labeling import ClusterLabel
from expertos.models import Synthesis, SynthesisMap, SynthesisMapEntry

MAP_TOKEN_LIMIT = 4000  # criterio 5
BYTES_PER_TOKEN = 2.5  # estimación deliberadamente pesimista; contraste real en A25


class SynthesisMapError(ValueError):
    """Las fuentes del mapa no coinciden, o el mapa no cabe en el tope del criterio 5."""


def map_text(synthesis_map: SynthesisMap) -> str:
    """El texto exacto que se persiste: es lo que se cuenta, no una versión compacta."""
    return synthesis_map.model_dump_json(indent=2) + "\n"


def count_map_tokens(synthesis_map: SynthesisMap) -> int:
    """Estimación offline de tokens del mapa; el proveedor del Orquestador aún no está decidido."""
    return math.ceil(len(map_text(synthesis_map).encode("utf-8")) / BYTES_PER_TOKEN)


def _check_sources(
    run_id: str,
    syntheses: Mapping[str, Synthesis],
    labels: Mapping[str, ClusterLabel],
    assignment: Mapping[str, str],
) -> list[str]:
    """Devuelve los `expert_id` en orden numérico; reúne todas las incoherencias antes de fallar."""
    expected = set(assignment.values())
    if not expected:
        raise SynthesisMapError(f"La partición {run_id} está vacía")

    problems: list[str] = []
    for name, found in (("síntesis", set(syntheses)), ("etiquetas", set(labels))):
        if found != expected:
            problems.append(
                f"{name}: faltan {sorted(expected - found)}, sobran {sorted(found - expected)}"
            )

    for expert_id in sorted(expected & set(syntheses)):
        synthesis = syntheses[expert_id]
        if not synthesis.synthesis_id.startswith(f"{run_id}/"):
            problems.append(f"{expert_id}: la síntesis {synthesis.synthesis_id} no es de {run_id}")
        members = {paper_id for paper_id, owner in assignment.items() if owner == expert_id}
        if set(synthesis.paper_ids) != members or len(synthesis.paper_ids) != len(members):
            problems.append(f"{expert_id}: los paper_ids de la síntesis no coinciden con la partición")
        if expert_id in labels and labels[expert_id].topic_label != synthesis.topic_label:
            problems.append(f"{expert_id}: topic_label distinto en la síntesis y en las etiquetas")

    if problems:
        raise SynthesisMapError("; ".join(problems))
    return sorted(expected, key=lambda e: int(e[1:]))


def build_synthesis_map(
    run_id: str,
    syntheses: Mapping[str, Synthesis],
    labels: Mapping[str, ClusterLabel],
    assignment: Mapping[str, str],
    *,
    updated_at: datetime | None = None,
    token_limit: int = MAP_TOKEN_LIMIT,
) -> SynthesisMap:
    """Arma el mapa; levanta `SynthesisMapError` si las fuentes discrepan o no cabe en `token_limit`."""
    expert_ids = _check_sources(run_id, syntheses, labels, assignment)
    synthesis_map = SynthesisMap(
        run_id=run_id,
        updated_at=updated_at or datetime.now(timezone.utc),
        entries=[
            SynthesisMapEntry(
                expert_id=expert_id,
                topic_label=syntheses[expert_id].topic_label,
                one_liner=labels[expert_id].one_liner,
                n_papers=len(syntheses[expert_id].paper_ids),
                keywords=list(labels[expert_id].keywords),
            )
            for expert_id in expert_ids
        ],
    )
    tokens = count_map_tokens(synthesis_map)
    if tokens > token_limit:
        raise SynthesisMapError(f"El mapa estima {tokens} tokens; el criterio 5 admite ≤ {token_limit}")
    return synthesis_map
