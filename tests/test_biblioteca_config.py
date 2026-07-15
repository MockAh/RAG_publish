"""Tests para biblioteca.config.Settings."""

from pathlib import Path

import pytest

from biblioteca.config import Settings


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Sin variables de entorno, `Settings` usa los defaults indicados."""
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo

    settings = Settings()

    assert settings.db_path == Path("data/excavador.db")
    assert settings.pdf_dir == Path("data/pdfs")
    assert settings.tei_dir == Path("data/tei")
    assert settings.chroma_dir == Path("data/chroma")
    assert settings.grobid_url == "http://localhost:8070"
    assert settings.embedding_model == "intfloat/multilingual-e5-large"
    assert settings.chunk_min_tokens == 200
    assert settings.chunk_max_tokens == 500


def test_settings_overrides_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Las variables de entorno `BIBLIOTECA_*` sobreescriben sus defaults."""
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo
    monkeypatch.setenv("BIBLIOTECA_DB_PATH", "otra/ruta.db")
    monkeypatch.setenv("BIBLIOTECA_PDF_DIR", "otra/pdfs")
    monkeypatch.setenv("BIBLIOTECA_TEI_DIR", "otra/tei")
    monkeypatch.setenv("BIBLIOTECA_CHROMA_DIR", "otra/chroma")
    monkeypatch.setenv("BIBLIOTECA_GROBID_URL", "http://otro-host:9090")
    monkeypatch.setenv("BIBLIOTECA_EMBEDDING_MODEL", "otro/modelo")
    monkeypatch.setenv("BIBLIOTECA_CHUNK_MIN_TOKENS", "100")
    monkeypatch.setenv("BIBLIOTECA_CHUNK_MAX_TOKENS", "400")

    settings = Settings()

    assert settings.db_path == Path("otra/ruta.db")
    assert settings.pdf_dir == Path("otra/pdfs")
    assert settings.tei_dir == Path("otra/tei")
    assert settings.chroma_dir == Path("otra/chroma")
    assert settings.grobid_url == "http://otro-host:9090"
    assert settings.embedding_model == "otro/modelo"
    assert settings.chunk_min_tokens == 100
    assert settings.chunk_max_tokens == 400
