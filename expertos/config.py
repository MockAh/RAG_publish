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
    deepseek_model: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    llm_rpm_synthesis: int = 2
    llm_rpm_label: int = 10
    llm_max_retries: int = 5
    db_path: Path = Path("data/excavador.db")
    chroma_dir: Path = Path("data/chroma")
    synthesis_dir: Path = Path("data/synthesis")
    expert_vectors_path: Path = Path("data/expert_vectors.npz")
    cluster_report_path: Path = Path("data/cluster_sweep_report.md")
    cluster_inspect_dir: Path = Path("data")
    cluster_run_id: str = "kmeans-k9-seed42-98b2c308"
    cluster_labels_path: Path = Path("data/cluster_labels.json")

    @field_validator(
        "llm_provider", "gemini_api_key", "model_synthesis", "model_label", "deepseek_api_key", "deepseek_model",
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
