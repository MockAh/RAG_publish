"""Tests para expertos.llm.GeminiClient."""

import sqlite3
from pathlib import Path
from unittest.mock import Mock

import pytest
from google.genai import errors
from pydantic import BaseModel, ValidationError

import expertos.llm as llm_module
from expertos.config import Settings
from expertos.llm import GeminiClient, LLMOutputError


class Ping(BaseModel):
    ok: bool


class _FakeUsage:
    def __init__(self, prompt_tokens: int | None, output_tokens: int | None) -> None:
        self.prompt_token_count = prompt_tokens
        self.candidates_token_count = output_tokens


class _FakeResponse:
    def __init__(self, text: str, prompt_tokens: int = 10, output_tokens: int = 5) -> None:
        self.text = text
        self.usage_metadata = _FakeUsage(prompt_tokens, output_tokens)


class _FakeModels:
    """Simula `client.models`, devolviendo respuestas/excepciones en orden."""

    def __init__(self, results: list) -> None:
        self._results = list(results)
        self.calls: list = []

    def generate_content(self, *, model, contents, config):
        self.calls.append((model, contents, config))
        item = self._results.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class _FakeClient:
    def __init__(self, results: list) -> None:
        self.models = _FakeModels(results)


def _client(tmp_path: Path, results: list, **kwargs) -> GeminiClient:
    fake = _FakeClient(results)
    client = GeminiClient(
        api_key="fake-key",
        model=kwargs.pop("model", "gemini-test"),
        rpm=kwargs.pop("rpm", 60),
        db_path=tmp_path / "expertos.db",
        client=fake,
        **kwargs,
    )
    client._sleep = Mock()  # type: ignore[method-assign]  # evita esperar el backoff real
    return client


def test_valid_json_returns_schema_instance(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo

    client = _client(tmp_path, [_FakeResponse('{"ok": true}')])

    result = client.complete_json("system", "user", Ping)

    assert result == Ping(ok=True)


def test_invalid_json_raises_llm_output_error_without_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo

    client = _client(tmp_path, [_FakeResponse("esto no es json")])

    with pytest.raises(LLMOutputError):
        client.complete_json("system", "user", Ping)

    assert len(client._client.models.calls) == 1


def test_response_not_matching_schema_raises_llm_output_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo

    client = _client(tmp_path, [_FakeResponse('{"otro_campo": 1}')])

    with pytest.raises(LLMOutputError):
        client.complete_json("system", "user", Ping)

    assert len(client._client.models.calls) == 1


def test_429_then_200_succeeds_and_logs_two_rows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo
    error_429 = errors.ClientError(429, {"message": "rate limited"})

    client = _client(tmp_path, [error_429, _FakeResponse('{"ok": true}')])

    result = client.complete_json("system", "user", Ping)

    assert result == Ping(ok=True)
    conn = sqlite3.connect(tmp_path / "expertos.db")
    rows = conn.execute("SELECT ok FROM llm_calls ORDER BY id").fetchall()
    assert [r[0] for r in rows] == [0, 1]


def test_400_raises_immediately_without_retry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo
    error_400 = errors.ClientError(400, {"message": "bad request"})

    client = _client(tmp_path, [error_400])

    with pytest.raises(errors.ClientError):
        client.complete_json("system", "user", Ping)

    assert len(client._client.models.calls) == 1
    conn = sqlite3.connect(tmp_path / "expertos.db")
    rows = conn.execute("SELECT ok FROM llm_calls").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == 0


def test_rate_limit_sleeps_between_consecutive_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo
    sleep_mock = Mock()
    monkeypatch.setattr(llm_module.time, "sleep", sleep_mock)
    fake = _FakeClient([_FakeResponse('{"ok": true}'), _FakeResponse('{"ok": true}')])
    client = GeminiClient(
        api_key="fake-key", model="gemini-test", rpm=10, db_path=tmp_path / "expertos.db", client=fake
    )

    client.complete_json("system", "user", Ping)
    client.complete_json("system", "user", Ping)

    positive_calls = [c for c in sleep_mock.call_args_list if c.args[0] > 0]
    assert positive_calls, "se esperaba al menos una espera positiva entre llamadas consecutivas"


def test_successful_call_logs_row_with_model_and_tokens(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo

    client = _client(
        tmp_path, [_FakeResponse('{"ok": true}', prompt_tokens=42, output_tokens=7)], model="gemini-x"
    )

    client.complete_json("system", "user", Ping)

    conn = sqlite3.connect(tmp_path / "expertos.db")
    row = conn.execute("SELECT model, input_tokens, output_tokens, ok FROM llm_calls").fetchone()
    assert row == ("gemini-x", 42, 7, 1)


def test_context_is_logged_as_json_on_every_attempt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo

    client = _client(
        tmp_path,
        [errors.ServerError(503, {"error": {"message": "high demand"}}), _FakeResponse('{"ok": true}')],
    )

    client.complete_json("system", "user", Ping, context={"task": "label", "expert_id": "C3"})

    conn = sqlite3.connect(tmp_path / "expertos.db")
    rows = conn.execute("SELECT ok, json_extract(context, '$.expert_id') FROM llm_calls ORDER BY id").fetchall()
    assert rows == [(0, "C3"), (1, "C3")]


def test_call_without_context_logs_null(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo

    client = _client(tmp_path, [_FakeResponse('{"ok": true}')])
    client.complete_json("system", "user", Ping)

    conn = sqlite3.connect(tmp_path / "expertos.db")
    assert conn.execute("SELECT context FROM llm_calls").fetchone() == (None,)


def test_old_table_without_context_column_is_migrated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo
    conn = sqlite3.connect(tmp_path / "expertos.db")
    conn.execute(
        "CREATE TABLE llm_calls (id INTEGER PRIMARY KEY, ts TEXT, provider TEXT, model TEXT,"
        " input_tokens INTEGER, output_tokens INTEGER, latency_ms INTEGER, ok INTEGER, error TEXT)"
    )
    conn.execute("INSERT INTO llm_calls (ts, ok) VALUES ('2026-09-27', 1)")
    conn.commit()

    client = _client(tmp_path, [_FakeResponse('{"ok": true}')])
    client.complete_json("system", "user", Ping, context={"expert_id": "C0"})

    rows = conn.execute("SELECT ts, context FROM llm_calls ORDER BY id").fetchall()
    assert rows[0] == ("2026-09-27", None)
    assert rows[1][1] == '{"expert_id": "C0"}'


@pytest.mark.slow
def test_real_call_against_model_label(tmp_path: Path) -> None:
    """Llamada real contra `model_label` (nunca `model_synthesis`, cuota diaria reservada)."""
    try:
        settings = Settings()
    except ValidationError:
        pytest.skip("Configuración de Expertos incompleta (falta EXPERTOS_GEMINI_API_KEY o modelos)")

    if not settings.gemini_api_key.get_secret_value():
        pytest.skip("EXPERTOS_GEMINI_API_KEY no configurada")
    client = GeminiClient(
        api_key=settings.gemini_api_key.get_secret_value(),
        model=settings.model_label,
        rpm=settings.llm_rpm_label,
        db_path=tmp_path / "expertos.db",
        max_retries=settings.llm_max_retries,
    )

    result = client.complete_json(
        "Responde únicamente con el schema pedido.", "Devuelve ok=true.", Ping
    )

    assert isinstance(result, Ping)
