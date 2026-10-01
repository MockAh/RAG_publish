"""Modelos de los contratos C3, C4 y C5 (`docs/01-CONTRATOS-DE-DATOS_v11.md`).

Los campos se transcriben exactamente del contrato, sin añadir ni renombrar: son la
frontera con la fase 05, y `test_expertos_models.py` compara los nombres 1:1. Lo que el
contrato deja en comentario (rangos de palabras) se vuelve validador que rechaza: lo que
llega al mapa del Orquestador no puede romper el contrato en silencio.

`SynthesisMap` (contenedor de las entradas C4) no está en el contrato: es decisión de
fase 04.

`stance` (C3) y `confidence` (C5) son juicios del LLM leyendo pasajes (L1, L2, A13):
aquí solo se restringen a sus literales, nunca se derivan de un score.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ONE_LINER_MAX_WORDS = 40
SUMMARY_MIN_WORDS = 300
SUMMARY_MAX_WORDS = 800


def check_one_liner(value: str) -> str:
    """Rechaza un `one_liner` de más de 40 palabras (C4; el mapa entero debe caber en un contexto)."""
    n_words = len(value.split())
    if n_words > ONE_LINER_MAX_WORDS:
        raise ValueError(f"one_liner tiene {n_words} palabras; C4 admite ≤ {ONE_LINER_MAX_WORDS}")
    return value


class Claim(BaseModel):
    """Afirmación atómica con los `chunk_id` que la sustentan (C3; también la usa C5).

    `supporting_chunks` vacío se rechaza: C3 no autoriza la lista vacía y D5 prohíbe
    afirmar sin `chunk_id`. Una claim sin soporte se descarta, no se repara (X3).
    """

    text: str  # afirmación atómica
    supporting_chunks: list[str] = Field(min_length=1)  # chunk_ids que la sustentan
    stance: Literal["supports", "contradicts", "mentions"]


class Synthesis(BaseModel):
    """C3 · salida de un Experto (offline), entrada del Mapa."""

    synthesis_id: str
    expert_id: str  # = cluster_id
    topic_label: str  # etiqueta humana del clúster
    summary: str  # 300–800 palabras
    key_claims: list[Claim]
    paper_ids: list[str]  # corpus que cubre
    updated_at: datetime

    @field_validator("summary")
    @classmethod
    def _summary_length(cls, value: str) -> str:
        n_words = len(value.split())
        if not SUMMARY_MIN_WORDS <= n_words <= SUMMARY_MAX_WORDS:
            raise ValueError(
                f"summary tiene {n_words} palabras; C3 exige {SUMMARY_MIN_WORDS}–{SUMMARY_MAX_WORDS}"
            )
        return value


class SynthesisMapEntry(BaseModel):
    """C4 · una fila del mapa que lee el Orquestador para rutear."""

    expert_id: str
    topic_label: str
    one_liner: str  # ≤ 40 palabras; el mapa completo debe caber en un contexto
    n_papers: int
    keywords: list[str]

    _one_liner_fits_c4 = field_validator("one_liner")(check_one_liner)


class SynthesisMap(BaseModel):
    """Contenedor de las entradas C4 (decisión de fase 04; las entradas son C4 literal).

    `run_id` ata el mapa a la partición de `clusters` de la que sale. Un `expert_id`
    repetido se rechaza: el Orquestador no podría rutear entre dos filas iguales.
    """

    run_id: str
    updated_at: datetime
    entries: list[SynthesisMapEntry]

    @model_validator(mode="after")
    def _unique_expert_ids(self) -> "SynthesisMap":
        ids = [entry.expert_id for entry in self.entries]
        duplicated = sorted({i for i in ids if ids.count(i) > 1})
        if duplicated:
            raise ValueError(f"expert_id repetido en el mapa: {', '.join(duplicated)}")
        return self


class ExpertAnswer(BaseModel):
    """C5 · respuesta de un Experto al Orquestador (online).

    `gaps` es obligatorio aunque admita `None` (el contrato no le da default): el
    Experto tiene que decir explícitamente si su corpus no cubre algo.
    """

    expert_id: str
    question: str
    answer: str  # prosa breve
    evidence: list[Claim]  # cada afirmación con sus chunk_ids
    confidence: Literal["high", "medium", "low"]
    gaps: str | None  # "mi corpus no cubre X"
