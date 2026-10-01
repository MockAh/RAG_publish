"""Tests para expertos.config.Settings."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from expertos.config import Settings


def test_settings_requires_gemini_api_key_and_models(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Sin las variables obligatorias ni `.env`, `Settings` debe fallar."""
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo

    with pytest.raises(ValidationError):
        Settings()


def test_settings_defaults_and_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Con las obligatorias presentes, el resto de campos usan sus defaults."""
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo
    monkeypatch.setenv("EXPERTOS_GEMINI_API_KEY", "sk-secreta")
    monkeypatch.setenv("EXPERTOS_MODEL_SYNTHESIS", "gemini-synthesis")
    monkeypatch.setenv("EXPERTOS_MODEL_LABEL", "gemini-label")

    settings = Settings()

    assert settings.gemini_api_key.get_secret_value() == "sk-secreta"
    assert settings.model_synthesis == "gemini-synthesis"
    assert settings.model_label == "gemini-label"
    assert settings.llm_rpm_synthesis == 2
    assert settings.llm_rpm_label == 10
    assert settings.llm_max_retries == 5
    assert settings.db_path == Path("data/excavador.db")
    assert settings.chroma_dir == Path("data/chroma")
    assert settings.synthesis_dir == Path("data/synthesis")
    assert settings.synthesis_map_path == Path("data/synthesis_map.json")
    assert settings.expert_vectors_path == Path("data/expert_vectors.npz")


def test_model_label_strips_crlf_from_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Un `.env` con `\\r\\n` (CRLF) en el valor no debe colarse en `model_label`."""
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo
    env_file = tmp_path / ".env"
    env_file.write_text(
        "EXPERTOS_GEMINI_API_KEY=sk-secreta\n"
        "EXPERTOS_MODEL_SYNTHESIS=gemini-synthesis\n"
        "EXPERTOS_MODEL_LABEL=gemini-2.5-flash\r\n"
    )

    settings = Settings()

    assert settings.model_label == "gemini-2.5-flash"


def test_repr_does_not_leak_api_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`repr(Settings())` no debe exponer el valor de la API key."""
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo
    monkeypatch.setenv("EXPERTOS_GEMINI_API_KEY", "sk-super-secreta")
    monkeypatch.setenv("EXPERTOS_MODEL_SYNTHESIS", "gemini-synthesis")
    monkeypatch.setenv("EXPERTOS_MODEL_LABEL", "gemini-label")

    settings = Settings()

    assert "sk-super-secreta" not in repr(settings)


def test_settings_ignores_foreign_env_vars_from_real_dotenv(tmp_path: Path) -> None:
    """Regresión: un `.env` con variables `EXCAVADOR_*` ajenas no debe romper `Settings` (sin chdir)."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "EXCAVADOR_OPENALEX_MAILTO=x@y.z\n"
        "EXPERTOS_GEMINI_API_KEY=sk-real\n"
        "EXPERTOS_MODEL_SYNTHESIS=gemini-synthesis\n"
        "EXPERTOS_MODEL_LABEL=gemini-label\n"
        "EXPERTOS_CHROMA_DIR=/tmp/foo\n"
    )

    settings = Settings(_env_file=env_file)

    assert settings.chroma_dir == Path("/tmp/foo")
    assert settings.gemini_api_key.get_secret_value() == "sk-real"
