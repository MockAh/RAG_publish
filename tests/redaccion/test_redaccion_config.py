"""Tests para redaccion.config.Settings."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from redaccion.config import Settings


def test_defaults_without_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo

    settings = Settings()

    assert settings.verifier_tray_size is None  # Y3: charola completa al arrancar
    assert settings.max_orchestrator_calls == 1  # Y11
    assert settings.max_experts == 4
    assert settings.max_writer_calls == 3
    assert settings.max_cycles == 3  # C7
    assert settings.exempt_alarm_ratio == 0.20  # Y8
    assert settings.audit_dir == Path("data/redaccion")


def test_shared_dotenv_with_foreign_prefixes_is_ignored(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Regla 3: el `.env` compartido trae EXCAVADOR_*/EXPERTOS_*; no deben romper `Settings`."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "EXCAVADOR_OPENALEX_EMAIL=x@example.org\n"
        "EXPERTOS_LLM_PROVIDER=deepseek\n"
        "EXPERTOS_DEEPSEEK_API_KEY=sk-ajena\n"
        "REDACCION_VERIFIER_TRAY_SIZE=1\r\n"
    )

    settings = Settings()

    assert settings.verifier_tray_size == 1
    assert "sk-ajena" not in repr(settings)


def test_env_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REDACCION_MAX_EXPERTS", "2")
    monkeypatch.setenv("REDACCION_AUDIT_DIR", "otra/ruta")

    settings = Settings()

    assert settings.max_experts == 2
    assert settings.audit_dir == Path("otra/ruta")


@pytest.mark.parametrize(
    ("var", "value"),
    [
        ("REDACCION_VERIFIER_TRAY_SIZE", "0"),
        ("REDACCION_MAX_EXPERTS", "5"),
        ("REDACCION_MAX_EXPERTS", "0"),
        ("REDACCION_EXEMPT_ALARM_RATIO", "1.5"),
    ],
)
def test_out_of_range_values_are_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, var: str, value: str) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(var, value)

    with pytest.raises(ValidationError):
        Settings()


def test_more_cycles_than_writer_calls_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Cada ciclo es una llamada al Redactor (Y11)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REDACCION_MAX_CYCLES", "4")

    with pytest.raises(ValidationError, match="MAX_CYCLES=4"):
        Settings()
