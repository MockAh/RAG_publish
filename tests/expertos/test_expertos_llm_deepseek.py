"""Tests para expertos.llm.DeepSeekClient y make_client (HTTP mockeado con pytest-httpx)."""

import json
import sqlite3
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from pydantic import BaseModel, ValidationError
from pytest_httpx import HTTPXMock

from expertos.config import Settings
from expertos.llm import DeepSeekClient, GeminiClient, LLMOutputError, make_client

URL = "https://api.deepseek.com/chat/completions"


class Ping(BaseModel):
    ok: bool


def _completion(content: str | None, prompt_tokens: int = 10, completion_tokens: int = 5) -> dict:
    """Cuerpo de una respuesta de `/chat/completions` con el formato de DeepSeek."""
    return {
        "id": "cmpl-test",
        "object": "chat.completion",
        "model": "deepseek-flash",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


def _client(tmp_path: Path, **kwargs) -> DeepSeekClient:
    client = DeepSeekClient(
        api_key=kwargs.pop("api_key", "sk-fake"),
        model=kwargs.pop("model", "deepseek-flash"),
        rpm=kwargs.pop("rpm", 60),
        db_path=tmp_path / "expertos.db",
        **kwargs,
    )
    client._sleep = Mock()  # type: ignore[method-assign]  # evita esperar el backoff y el rate limit reales
    return client


def _rows(tmp_path: Path, columns: str = "ok") -> list[tuple]:
    conn = sqlite3.connect(tmp_path / "expertos.db")
    return conn.execute(f"SELECT {columns} FROM llm_calls ORDER BY id").fetchall()


# --- respuesta válida e inválida ------------------------------------------------


def test_valid_json_returns_schema_instance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo
    httpx_mock.add_response(url=URL, method="POST", json=_completion('{"ok": true}'))

    result = _client(tmp_path).complete_json("system", "user", Ping)

    assert result == Ping(ok=True)


def test_request_carries_model_json_mode_schema_and_bearer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo
    httpx_mock.add_response(url=URL, method="POST", json=_completion('{"ok": true}'))

    _client(tmp_path, api_key="sk-secreta", model="deepseek-x").complete_json("Sistema base.", "Pregunta.", Ping)

    request = httpx_mock.get_request()
    assert request.headers["Authorization"] == "Bearer sk-secreta"
    body = json.loads(request.content)
    assert body["model"] == "deepseek-x"
    assert body["response_format"] == {"type": "json_object"}
    assert body["stream"] is False
    system, user = body["messages"]
    assert system["role"] == "system" and user == {"role": "user", "content": "Pregunta."}
    # El modo JSON exige la palabra «json» en el prompt; el schema viaja ahí.
    assert system["content"].startswith("Sistema base.")
    assert "JSON" in system["content"]
    assert json.dumps(Ping.model_json_schema(), ensure_ascii=False) in system["content"]


def test_custom_base_url_is_used(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo
    httpx_mock.add_response(url="https://proxy.test/v1/chat/completions", json=_completion('{"ok": true}'))

    _client(tmp_path, base_url="https://proxy.test/v1/").complete_json("s", "u", Ping)


def test_invalid_json_raises_llm_output_error_without_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo
    httpx_mock.add_response(url=URL, method="POST", json=_completion("esto no es json"))

    with pytest.raises(LLMOutputError):
        _client(tmp_path).complete_json("system", "user", Ping)

    assert len(httpx_mock.get_requests()) == 1
    assert _rows(tmp_path) == [(0,)]


def test_json_not_matching_schema_raises_llm_output_error_without_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo
    httpx_mock.add_response(url=URL, method="POST", json=_completion('{"otro_campo": 1}'))

    with pytest.raises(LLMOutputError):
        _client(tmp_path).complete_json("system", "user", Ping)

    assert len(httpx_mock.get_requests()) == 1


@pytest.mark.parametrize("content", [None, ""])
def test_empty_content_raises_llm_output_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, httpx_mock: HTTPXMock, content: str | None
) -> None:
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo
    httpx_mock.add_response(url=URL, method="POST", json=_completion(content))

    with pytest.raises(LLMOutputError):
        _client(tmp_path).complete_json("system", "user", Ping)

    assert len(httpx_mock.get_requests()) == 1


# --- reintentos -----------------------------------------------------------------


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_retryable_status_then_200_succeeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, httpx_mock: HTTPXMock, status: int
) -> None:
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo
    httpx_mock.add_response(url=URL, method="POST", status_code=status, json={"error": {"message": "busy"}})
    httpx_mock.add_response(url=URL, method="POST", json=_completion('{"ok": true}'))
    client = _client(tmp_path)

    result = client.complete_json("system", "user", Ping)

    assert result == Ping(ok=True)
    assert len(httpx_mock.get_requests()) == 2
    assert _rows(tmp_path) == [(0,), (1,)]
    assert client._sleep.call_count >= 1  # hubo backoff antes del segundo intento


def test_timeout_is_retried(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo
    httpx_mock.add_exception(httpx.ReadTimeout("lento"), url=URL)
    httpx_mock.add_response(url=URL, method="POST", json=_completion('{"ok": true}'))

    assert _client(tmp_path).complete_json("system", "user", Ping) == Ping(ok=True)
    assert len(httpx_mock.get_requests()) == 2


@pytest.mark.httpx_mock(can_send_already_matched_responses=True)
def test_persistent_503_gives_up_after_max_retries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo
    httpx_mock.add_response(url=URL, method="POST", status_code=503, text="Service Unavailable")

    with pytest.raises(httpx.HTTPStatusError):
        _client(tmp_path, max_retries=3).complete_json("system", "user", Ping)

    assert len(httpx_mock.get_requests()) == 3
    assert _rows(tmp_path) == [(0,), (0,), (0,)]


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (401, "Authentication Fails, Your api key is invalid"),
        (402, "Insufficient Balance"),
        (422, "Invalid Parameters"),
        (400, "Invalid Format"),
    ],
)
def test_client_errors_raise_immediately_and_log_body(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, httpx_mock: HTTPXMock, status: int, message: str
) -> None:
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo
    httpx_mock.add_response(url=URL, method="POST", status_code=status, json={"error": {"message": message}})

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        _client(tmp_path).complete_json("system", "user", Ping)

    assert exc_info.value.response.status_code == status
    assert len(httpx_mock.get_requests()) == 1
    # El motivo del cuerpo llega a `llm_calls.error`: diagnosticar sin relanzar (F5).
    [(ok, error)] = _rows(tmp_path, "ok, error")
    assert ok == 0
    assert str(status) in error and message in error


# --- rate limit -----------------------------------------------------------------


def test_rate_limit_sleeps_min_interval_between_consecutive_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo
    httpx_mock.add_response(url=URL, method="POST", json=_completion('{"ok": true}'))
    httpx_mock.add_response(url=URL, method="POST", json=_completion('{"ok": true}'))
    client = _client(tmp_path, rpm=10)  # 6 s entre llamadas

    client.complete_json("system", "user", Ping)
    client._sleep.assert_not_called()  # la primera no espera
    client.complete_json("system", "user", Ping)

    [call] = client._sleep.call_args_list
    assert 5.0 < call.args[0] <= 6.0


# --- registro en llm_calls ------------------------------------------------------


def test_successful_call_logs_provider_model_tokens_and_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo
    httpx_mock.add_response(url=URL, method="POST", json=_completion('{"ok": true}', 147, 30))

    _client(tmp_path, model="deepseek-flash").complete_json(
        "system", "user", Ping, context={"task": "label", "expert_id": "C3"}
    )

    rows = _rows(tmp_path, "provider, model, input_tokens, output_tokens, ok, error, json_extract(context, '$.expert_id')")
    assert rows == [("deepseek", "deepseek-flash", 147, 30, 1, None, "C3")]
    [(input_type, output_type)] = _rows(tmp_path, "typeof(input_tokens), typeof(output_tokens)")
    assert (input_type, output_type) == ("integer", "integer")


def test_context_is_logged_on_every_attempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo
    httpx_mock.add_response(url=URL, method="POST", status_code=503, text="busy")
    httpx_mock.add_response(url=URL, method="POST", json=_completion('{"ok": true}'))

    _client(tmp_path).complete_json("system", "user", Ping, context={"task": "label", "expert_id": "C7"})

    rows = _rows(tmp_path, "provider, ok, json_extract(context, '$.expert_id')")
    assert rows == [("deepseek", 0, "C7"), ("deepseek", 1, "C7")]


def test_missing_usage_logs_null_tokens(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo
    body = _completion('{"ok": true}')
    del body["usage"]
    httpx_mock.add_response(url=URL, method="POST", json=body)

    _client(tmp_path).complete_json("system", "user", Ping)

    assert _rows(tmp_path, "input_tokens, output_tokens, ok") == [(None, None, 1)]


# --- make_client y Settings -----------------------------------------------------


def _settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "gemini_api_key": "g-fake",
        "model_synthesis": "gemini-s",
        "model_label": "gemini-l",
        "db_path": tmp_path / "expertos.db",
        **overrides,
    }
    return Settings(_env_file=None, **values)


def test_make_client_deepseek_uses_deepseek_model_and_task_rpm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo
    settings = _settings(
        tmp_path,
        llm_provider="deepseek",
        deepseek_api_key="sk-fake",
        deepseek_model="deepseek-flash",
        llm_rpm_label=10,
        llm_rpm_synthesis=2,
    )

    label = make_client("label", settings)
    synthesis = make_client("synthesis", settings)

    assert isinstance(label, DeepSeekClient) and isinstance(synthesis, DeepSeekClient)
    assert label.model == synthesis.model == "deepseek-flash"
    assert label.min_interval_s == 6.0
    assert synthesis.min_interval_s == 30.0


def test_make_client_gemini_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo

    client = make_client("label", _settings(tmp_path))

    assert isinstance(client, GeminiClient)
    assert client.model == "gemini-l"


def test_make_client_rejects_unknown_task(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo

    with pytest.raises(ValueError, match="task desconocida"):
        make_client("resumen", _settings(tmp_path))


@pytest.mark.parametrize(
    ("overrides", "missing"),
    [
        ({"deepseek_model": "deepseek-flash"}, "EXPERTOS_DEEPSEEK_API_KEY"),
        ({"deepseek_api_key": "sk-fake"}, "EXPERTOS_DEEPSEEK_MODEL"),
        ({"deepseek_api_key": "  ", "deepseek_model": "deepseek-flash"}, "EXPERTOS_DEEPSEEK_API_KEY"),
    ],
)
def test_deepseek_provider_requires_key_and_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, overrides: dict, missing: str
) -> None:
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo

    with pytest.raises(ValidationError, match=missing):
        _settings(tmp_path, llm_provider="deepseek", **overrides)


def test_deepseek_settings_strip_crlf(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)  # cwd sin .env: no hereda config del repo

    settings = _settings(
        tmp_path, llm_provider="deepseek\r", deepseek_api_key="sk-fake\r", deepseek_model="deepseek-flash\r"
    )

    assert settings.llm_provider == "deepseek"
    assert settings.deepseek_api_key.get_secret_value() == "sk-fake"
    assert settings.deepseek_model == "deepseek-flash"
