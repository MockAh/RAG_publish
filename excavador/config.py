"""Configuración del Excavador.

Lee variables de entorno con prefijo ``EXCAVADOR_`` y, opcionalmente, un
archivo ``.env`` en la raíz del proyecto.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración global del Excavador."""

    model_config = SettingsConfigDict(env_prefix="EXCAVADOR_", env_file=".env")

    db_path: Path = Path("data/excavador.db")
    pdf_dir: Path = Path("data/pdfs")
    relevance_threshold: float = 0.78
    snowball_k: int = 15
    openalex_mailto: str
    semanticscholar_api_key: str | None = None
    embedding_model: str = "intfloat/multilingual-e5-large"
