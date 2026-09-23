"""Cliente LLM (Gemini) para los Expertos.

Provee rate limiting (mínimo intervalo entre llamadas), reintentos con
`tenacity` y registro de cada llamada (éxito o fallo) en SQLite.
"""

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, TypeVar

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

T = TypeVar("T", bound=BaseModel)

_CREATE_LLM_CALLS = """
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY,
    ts TEXT,
    provider TEXT,
    model TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    latency_ms INTEGER,
    ok INTEGER,
    error TEXT
)
"""


class LLMOutputError(Exception):
    """El LLM devolvió un texto que no es JSON válido o no cumple el schema."""


class LLMClient(Protocol):
    """Protocolo de un cliente LLM que devuelve respuestas tipadas por schema."""

    def complete_json(self, system: str, user: str, schema: type[T]) -> T:
        """Genera contenido y lo valida contra `schema`."""
        ...


def _is_retryable(exc: BaseException) -> bool:
    """Solo se reintenta ante 429, 5xx o timeouts; cualquier otro error se levanta de inmediato."""
    if isinstance(exc, errors.ServerError):
        return True
    if isinstance(exc, errors.ClientError):
        return exc.code == 429
    if isinstance(exc, httpx.TimeoutException):
        return True
    return False


class GeminiClient:
    """Cliente Gemini con rate limiting por instancia y registro de llamadas en SQLite."""

    def __init__(
        self,
        api_key: str,
        model: str,
        rpm: int,
        db_path: Path,
        max_retries: int = 5,
        client: Any | None = None,
    ) -> None:
        self.model = model
        self.min_interval_s = 60.0 / rpm
        self.max_retries = max_retries
        self.db_path = Path(db_path)
        self._last_call_at: float | None = None
        self._client = client if client is not None else genai.Client(api_key=api_key)

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute(_CREATE_LLM_CALLS)
        self._conn.commit()

    def _sleep(self, seconds: float) -> None:
        """Duerme `seconds`. Aislado en un método para poder parchearlo en tests."""
        time.sleep(seconds)

    def _apply_rate_limit(self) -> None:
        """Duerme lo necesario para respetar `min_interval_s` entre llamadas."""
        now = time.monotonic()
        if self._last_call_at is not None:
            elapsed = now - self._last_call_at
            remaining = self.min_interval_s - elapsed
            if remaining > 0:
                self._sleep(remaining)
        self._last_call_at = time.monotonic()

    def _log_call(
        self,
        latency_ms: int,
        ok: bool,
        error: str | None,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO llm_calls (ts, provider, model, input_tokens, output_tokens, latency_ms, ok, error)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                "gemini",
                self.model,
                input_tokens,
                output_tokens,
                latency_ms,
                1 if ok else 0,
                error,
            ),
        )
        self._conn.commit()

    def complete_json(self, system: str, user: str, schema: type[T]) -> T:
        """Genera contenido con `system`/`user` y lo valida contra `schema`.

        Reintenta solo ante 429/5xx/timeouts (backoff exponencial). Un
        `LLMOutputError` (JSON inválido o que no cumple el schema) no se
        reintenta. Cada intento, exitoso o no, escribe su propia fila en
        `llm_calls`.
        """

        @retry(
            reraise=True,
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=2, max=60),
            retry=retry_if_exception(_is_retryable),
            sleep=self._sleep,
        )
        def _do_call() -> T:
            self._apply_rate_limit()
            start = time.monotonic()
            try:
                response = self._client.models.generate_content(
                    model=self.model,
                    contents=user,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        response_mime_type="application/json",
                        response_schema=schema,
                    ),
                )
            except Exception as exc:
                latency_ms = int((time.monotonic() - start) * 1000)
                self._log_call(latency_ms, ok=False, error=str(exc), input_tokens=None, output_tokens=None)
                raise

            latency_ms = int((time.monotonic() - start) * 1000)
            usage = response.usage_metadata
            input_tokens = _to_native_int(usage.prompt_token_count) if usage else None
            output_tokens = _to_native_int(usage.candidates_token_count) if usage else None

            try:
                result = schema.model_validate_json(response.text)
            except Exception as exc:
                self._log_call(
                    latency_ms, ok=False, error=str(exc), input_tokens=input_tokens, output_tokens=output_tokens
                )
                raise LLMOutputError(
                    f"Respuesta del LLM inválida contra el schema {schema.__name__}: {exc}. "
                    f"Texto crudo: {response.text!r}"
                ) from exc

            self._log_call(latency_ms, ok=True, error=None, input_tokens=input_tokens, output_tokens=output_tokens)
            return result

        return _do_call()


def _to_native_int(value: Any) -> int | None:
    """Convierte un contador de tokens del SDK a `int` nativo (o `None`)."""
    return int(value) if value is not None else None
