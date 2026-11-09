"""Modelos de los contratos C6 y C7 (`docs/01-CONTRATOS-DE-DATOS_v11.md`) y registro por pieza (Y7).

C6 y C7 se transcriben literales, sin añadir ni renombrar campos (R0: «ningún contrato
cambia»). `test_redaccion_models.py` compara los nombres 1:1 con el documento.

El registro por pieza (`PieceRecord`, `PieceLog`) es un modelo interno de fase 05, como
`ConsultRecord` en fase 04, y no es contrato. C7 solo lista fallos; el criterio 1 (≥ 90 % de
oraciones factuales verificadas) necesita también los aciertos. Por eso el registro exige un
veredicto explícito por cada `chunk_id` citado, `ok` incluido: una pieza sin veredicto es un
error, no un acierto (Y7).

Glosario de la panadería: pieza = oración; libro de inspección = `PieceLog`.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

FailureReason = Literal["not_entailed", "scope_mismatch", "chunk_not_found"]
Verdict = Literal["ok", "not_entailed", "scope_mismatch", "chunk_not_found"]  # "ok" + motivos de C7


# --- C6 / C7 (literales) ----------------------------------------------------------


class DraftSection(BaseModel):
    """C6 · salida del Redactor, entrada del Verificador.

    Sin validadores: la coherencia entre marcadores `[n]` y `citations` la comprueba y
    registra el código del Redactor (Y5, Y6) en vez de rechazar el borrador entero.
    """

    text: str  # prosa con marcadores [1], [2], ...
    citations: dict[int, list[str]]  # nº de cita → chunk_ids
    unsupported_marked: bool  # las afirmaciones sin cita van marcadas ⟨sin fuente⟩


class CitationFailure(BaseModel):
    """C7 · un par (oración, chunk) que el Verificador no da por bueno."""

    sentence: str
    chunk_id: str
    reason: FailureReason


class VerificationReport(BaseModel):
    """C7 · salida del Verificador.

    `passed=True` con fallos se rechaza: el Orquestador no devolvería el reporte al Redactor
    y los fallos se perderían. `passed=False` sin fallos sí se admite: un pedido puede fallar
    por piezas ⟨sin fuente⟩ (Y8), que no tienen `chunk_id` y no caben en `CitationFailure`.
    """

    passed: bool
    failures: list[CitationFailure]

    @model_validator(mode="after")
    def _passed_means_no_failures(self) -> "VerificationReport":
        if self.passed and self.failures:
            raise ValueError(f"passed=True con {len(self.failures)} fallo(s)")
        return self


# --- Registro por pieza (Y7; interno) ---------------------------------------------


class ChunkVerdict(BaseModel):
    """Veredicto explícito del Verificador (o del código, si es `chunk_not_found`) para un chunk."""

    chunk_id: str
    verdict: Verdict
    reason: str  # motivo: explicación del Verificador o causa registrada por el código


PieceKind = Literal["factual", "transition", "meta"]  # Y8: solo transición y meta-texto son exentas
PairRole = Literal["attribution", "objection"]  # Y9: pieza que viene de un par supports/contradicts
PieceStatus = Literal[
    "verified",  # factual, citada, todos sus chunks `ok`
    "failed",  # factual, citada, algún chunk no `ok` (vuelve al Redactor si quedan ciclos)
    "unsupported",  # factual sin cita → ⟨sin fuente⟩; cuenta como fallo (Y8)
    "unverified",  # ⟨sin verificar⟩: ciclos agotados o pedido cortado por presupuesto (Y11)
    "exempt",  # transición o meta-texto (Y8)
]


class PieceRecord(BaseModel):
    """Una pieza (oración) en un ciclo de verificación.

    `index` es el índice estable que asigna la segmentación por código (Y6); con `cycle`
    identifica la fila. `status` se guarda para que la auditoría se lea sin recalcular, y el
    validador comprueba que concuerda con `kind`, `chunk_ids` y `verdicts`.
    """

    index: int = Field(ge=0)
    cycle: int = Field(ge=1)
    text: str  # texto exacto de la pieza (C7 identifica la oración por su texto)
    kind: PieceKind
    pair_role: PairRole | None
    chunk_ids: list[str]
    verdicts: list[ChunkVerdict]
    status: PieceStatus

    @model_validator(mode="after")
    def _status_matches_content(self) -> "PieceRecord":
        cited = set(self.chunk_ids)
        judged = [v.chunk_id for v in self.verdicts]
        if len(cited) != len(self.chunk_ids):
            raise ValueError(f"pieza {self.index}: chunk_id repetido")
        if len(set(judged)) != len(judged):
            raise ValueError(f"pieza {self.index}: más de un veredicto para el mismo chunk_id")
        if not set(judged) <= cited:
            raise ValueError(f"pieza {self.index}: veredicto para un chunk que la pieza no cita")

        exempt = self.kind != "factual"
        if exempt != (self.status == "exempt"):
            raise ValueError(f"pieza {self.index}: kind={self.kind!r} incompatible con status={self.status!r}")
        if self.status in ("exempt", "unsupported"):
            if self.verdicts:
                raise ValueError(f"pieza {self.index}: status={self.status!r} no lleva veredictos")
            if self.status == "unsupported" and self.chunk_ids:
                raise ValueError(f"pieza {self.index}: unsupported (⟨sin fuente⟩) no lleva chunk_ids")
        elif self.status in ("verified", "failed"):
            if not cited:
                raise ValueError(f"pieza {self.index}: status={self.status!r} sin chunk_ids")
            missing = cited - set(judged)
            if missing:
                raise ValueError(f"pieza {self.index}: sin veredicto para {sorted(missing)} (Y7)")
            all_ok = all(v.verdict == "ok" for v in self.verdicts)
            if all_ok != (self.status == "verified"):
                raise ValueError(f"pieza {self.index}: status={self.status!r} no concuerda con los veredictos")
        # "unverified": veredictos parciales o ausentes (corte por presupuesto, Y11) son legítimos.
        return self


class PieceLog(BaseModel):
    """Libro de inspección de una consulta: todas las piezas de todos los ciclos."""

    consultation_id: str
    pieces: list[PieceRecord]

    @model_validator(mode="after")
    def _unique_index_per_cycle(self) -> "PieceLog":
        keys = [(p.index, p.cycle) for p in self.pieces]
        duplicated = sorted({k for k in keys if keys.count(k) > 1})
        if duplicated:
            raise ValueError(f"(index, cycle) repetido en el registro: {duplicated}")
        return self
