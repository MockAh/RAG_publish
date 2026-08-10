"""Configuración de la Biblioteca.

Lee variables de entorno con prefijo ``BIBLIOTECA_`` y, opcionalmente, un
archivo ``.env`` en la raíz del proyecto.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración global de la Biblioteca."""

    # extra="ignore": el .env del repo trae variables EXCAVADOR_* ajenas a este modelo
    model_config = SettingsConfigDict(env_prefix="BIBLIOTECA_", env_file=".env", extra="ignore")

    db_path: Path = Path("data/excavador.db")
    pdf_dir: Path = Path("data/pdfs")
    tei_dir: Path = Path("data/tei")
    text_dir: Path = Path("data/text")
    chroma_dir: Path = Path("data/chroma")
    grobid_url: str = "http://localhost:8070"
    embedding_model: str = "intfloat/multilingual-e5-large"
    chunk_min_tokens: int = 200
    chunk_max_tokens: int = 500
