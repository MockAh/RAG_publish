"""Configuración de Redacción (fase 05).

Lee variables de entorno con prefijo ``REDACCION_`` y, opcionalmente, el ``.env`` de la raíz
del proyecto. Ningún campo es obligatorio en R1: proveedor y modelo del Verificador se fijan
con llamadas reales en R2 (Y2), y el Orquestador y el Redactor reutilizan `expertos.llm` (Y1).
"""

from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración global de Redacción."""

    # extra="ignore": el .env del repo trae variables EXCAVADOR_*/EXPERTOS_* ajenas a este modelo
    # (regla 3 de CLAUDE.md; A1 de fase 04, A11 de fase 03).
    model_config = SettingsConfigDict(env_prefix="REDACCION_", env_file=".env", extra="ignore")

    # Y3: piezas por llamada al Verificador. None = charola completa (arranque); 1 = pieza por pieza.
    # R11–R12 comparan ambos modos y R12 fija el valor.
    verifier_tray_size: int | None = Field(default=None, ge=1)
    # Y11: tope de llamadas por puesto en un pedido. El Verificador se cuenta en piezas, no aquí.
    max_orchestrator_calls: int = Field(default=1, ge=1)
    max_experts: int = Field(default=4, ge=1, le=4)  # spec: 1–4 Expertos por encargo
    max_writer_calls: int = Field(default=3, ge=1)
    # C7: máximo de ciclos Redactor ⇄ Verificador; después, ⟨sin verificar⟩.
    max_cycles: int = Field(default=3, ge=1)
    # Y8: alarma si la proporción de piezas exentas (transición/meta-texto) supera este valor.
    exempt_alarm_ratio: float = Field(default=0.20, gt=0, lt=1)
    # Auditoría en disco por consulta (Y5, Y7), un subdirectorio por `consultation_id`.
    audit_dir: Path = Path("data/redaccion")

    @model_validator(mode="after")
    def _writer_calls_cover_cycles(self) -> "Settings":
        """Cada ciclo es una llamada al Redactor: más ciclos que llamadas no se pueden cumplir."""
        if self.max_cycles > self.max_writer_calls:
            raise ValueError(
                f"REDACCION_MAX_CYCLES={self.max_cycles} supera REDACCION_MAX_WRITER_CALLS={self.max_writer_calls}"
            )
        return self
