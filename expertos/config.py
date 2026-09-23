"""Configuración de Expertos.

Lee variables de entorno con prefijo ``EXPERTOS_`` y, opcionalmente, un
archivo ``.env`` en la raíz del proyecto.
"""

from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración global de Expertos."""

    # extra="ignore": el .env del repo trae variables EXCAVADOR_*/BIBLIOTECA_* ajenas a este modelo
    model_config = SettingsConfigDict(env_prefix="EXPERTOS_", env_file=".env", extra="ignore")

    gemini_api_key: SecretStr
    model_synthesis: str
    model_label: str
    llm_rpm_synthesis: int = 2
    llm_rpm_label: int = 10
    llm_max_retries: int = 5
    db_path: Path = Path("data/excavador.db")
    chroma_dir: Path = Path("data/chroma")
    synthesis_dir: Path = Path("data/synthesis")

    @field_validator("gemini_api_key", "model_synthesis", "model_label", mode="before")
    @classmethod
    def _strip_whitespace(cls, value: object) -> object:
        """Descarta un `\\r` (CRLF de `.env`) u otros espacios colados que darían un 401/404 desconcertante."""
        return value.strip() if isinstance(value, str) else value
