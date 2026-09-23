"""Tests para excavador.config.Settings."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from excavador.config import Settings


def test_settings_defaults_with_required_mailto(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`openalex_mailto` es obligatorio; el resto de campos usan sus defaults."""
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda el mailto del repo    
    monkeypatch.setenv("EXCAVADOR_OPENALEX_MAILTO", "test@example.com")

    settings = Settings()

    assert settings.openalex_mailto == "test@example.com"
    assert settings.db_path == Path("data/excavador.db")
    assert settings.pdf_dir == Path("data/pdfs")
    assert settings.relevance_threshold == 0.78
    assert settings.snowball_k == 15
    assert settings.semanticscholar_api_key is None
    assert settings.embedding_model == "intfloat/multilingual-e5-large"


def test_settings_missing_mailto_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Sin `EXCAVADOR_OPENALEX_MAILTO` ni `.env`, Settings debe fallar."""
    monkeypatch.delenv("EXCAVADOR_OPENALEX_MAILTO", raising=False)
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda el mailto del repo

    with pytest.raises(ValidationError):
        Settings()


def test_settings_overrides_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Las variables de entorno sobreescriben sus defaults correspondientes."""
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo
    monkeypatch.setenv("EXCAVADOR_OPENALEX_MAILTO", "otro@example.com")
    monkeypatch.setenv("EXCAVADOR_DB_PATH", "otra/ruta.db")
    monkeypatch.setenv("EXCAVADOR_PDF_DIR", "otra/pdfs")
    monkeypatch.setenv("EXCAVADOR_RELEVANCE_THRESHOLD", "0.5")
    monkeypatch.setenv("EXCAVADOR_SNOWBALL_K", "20")
    monkeypatch.setenv("EXCAVADOR_SEMANTICSCHOLAR_API_KEY", "clave-secreta")
    monkeypatch.setenv("EXCAVADOR_EMBEDDING_MODEL", "otro/modelo")

    settings = Settings()

    assert settings.db_path == Path("otra/ruta.db")
    assert settings.pdf_dir == Path("otra/pdfs")
    assert settings.relevance_threshold == 0.5
    assert settings.snowball_k == 20
    assert settings.semanticscholar_api_key == "clave-secreta"
    assert settings.embedding_model == "otro/modelo"
