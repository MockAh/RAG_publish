"""Configuración de Expertos.

Lee variables de entorno con prefijo ``EXPERTOS_`` y, opcionalmente, un
archivo ``.env`` en la raíz del proyecto.
"""

from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración global de Expertos."""

    # extra="ignore": el .env del repo trae variables EXCAVADOR_*/BIBLIOTECA_* ajenas a este modelo
    model_config = SettingsConfigDict(env_prefix="EXPERTOS_", env_file=".env", extra="ignore")

    # Proveedor de síntesis y etiquetado (X6‴). Gemini sigue configurado: es el alternativo para D11.
    llm_provider: Literal["gemini", "deepseek"] = "gemini"
    gemini_api_key: SecretStr
    model_synthesis: str
    model_label: str
    deepseek_api_key: SecretStr | None = None
    deepseek_model: str | None = None  # etiquetado (N5)
    # Síntesis (N7–N9) con modelo propio, separado del de etiquetado. v4-pro por la comparación de N8 (A20).
    deepseek_model_synthesis: str = "deepseek-v4-pro"
    # El modelo razona y el razonamiento cuenta como salida (C8 de N7: 3 459 tokens para 12 frases);
    # un borrador de N8 (summary 300–800 palabras + claims) no cabe en los 4 096 del etiquetado.
    # 8192 se quedó corto en el primer borrador real (C8, `llm_calls` id 83). Las fuentes consultadas
    # (de terceros, no la documentación oficial) dan hasta 384K de salida para la serie V4.
    deepseek_max_tokens_synthesis: int = 32768
    deepseek_base_url: str = "https://api.deepseek.com"
    llm_rpm_synthesis: int = 2
    llm_rpm_label: int = 10
    llm_max_retries: int = 5
    db_path: Path = Path("data/excavador.db")
    chroma_dir: Path = Path("data/chroma")
    synthesis_dir: Path = Path("data/synthesis")
    synthesis_map_path: Path = Path("data/synthesis_map.json")
    consult_dir: Path = Path("data/consult")  # auditoría del modo consulta (N12)
    traps_dir: Path = Path("data/consult_traps")  # preguntas trampa y control (N13)
    traps_report_path: Path = Path("data/synthesis/_review/N13-trampas.md")
    review_path: Path = Path("data/synthesis/_review/N10-muestra.md")  # muestreo manual (N10)
    expert_vectors_path: Path = Path("data/expert_vectors.npz")
    cluster_report_path: Path = Path("data/cluster_sweep_report.md")
    cluster_inspect_dir: Path = Path("data")
    cluster_run_id: str = "kmeans-k9-seed42-98b2c308"
    cluster_labels_path: Path = Path("data/cluster_labels.json")

    @field_validator(
        "llm_provider", "gemini_api_key", "model_synthesis", "model_label", "deepseek_api_key", "deepseek_model",
        "deepseek_model_synthesis",
        mode="before",
    )
    @classmethod
    def _strip_whitespace(cls, value: object) -> object:
        """Descarta un `\\r` (CRLF de `.env`) u otros espacios colados que darían un 401/404 desconcertante."""
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _deepseek_needs_key_and_model(self) -> "Settings":
        """Con `llm_provider=deepseek`, faltar la clave o el modelo es un error de arranque, no un 401 a mitad de corrida."""
        if self.llm_provider == "deepseek":
            missing = [
                name
                for name, value in (("EXPERTOS_DEEPSEEK_API_KEY", self.deepseek_api_key), ("EXPERTOS_DEEPSEEK_MODEL", self.deepseek_model))
                if not value or (isinstance(value, SecretStr) and not value.get_secret_value())
            ]
            if missing:
                raise ValueError(f"EXPERTOS_LLM_PROVIDER=deepseek exige {', '.join(missing)}")
        return self
