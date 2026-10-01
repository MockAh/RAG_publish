"""Clientes LLM de los Expertos (Gemini y DeepSeek) tras un mismo protocolo.

Ambos comparten rate limiting (mínimo intervalo entre llamadas), reintentos con
`tenacity` y registro de cada llamada (éxito o fallo) en SQLite; solo difieren
en cómo generan el texto (`_generate`). `make_client(task, settings)` devuelve
el del proveedor configurado en `EXPERTOS_LLM_PROVIDER`. Gemini se conserva
como proveedor alternativo para D11 (Redactor y Verificador con proveedores
distintos en fase 05).

`llm_calls.context` guarda, como JSON, para qué se hizo la llamada (p. ej.
`{"expert_id": "C3", "run_id": …, "task": "label"}`): sin él, un 503 en mitad de
una corrida no dice qué clúster falló. Se consulta con `json_extract(context, '$.expert_id')`.
"""

import json
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

from expertos.config import Settings

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
    error TEXT,
    context TEXT
)
"""


class LLMOutputError(Exception):
    """El LLM devolvió un texto que no es JSON válido o no cumple el schema."""


class LLMClient(Protocol):
    """Protocolo de un cliente LLM que devuelve respuestas tipadas por schema."""

    def complete_json(
        self, system: str, user: str, schema: type[T], *, context: dict[str, str] | None = None
    ) -> T:
        """Genera contenido y lo valida contra `schema`; `context` identifica la llamada en el registro."""
        ...


def _is_retryable(exc: BaseException) -> bool:
    """Solo se reintenta ante 429, 5xx o timeouts; cualquier otro error se levanta de inmediato."""
    if isinstance(exc, errors.ServerError):
        return True
    if isinstance(exc, errors.ClientError):
        return exc.code == 429
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    if isinstance(exc, httpx.TimeoutException):
        return True
    return False


class _LoggedLLMClient:
    """Base común: rate limiting por instancia, reintentos y registro en `llm_calls`.

    Las subclases implementan `_generate`, que devuelve el texto crudo y los
    contadores de tokens, o levanta la excepción del proveedor.
    """

    provider: str

    def __init__(self, model: str, rpm: int, db_path: Path, max_retries: int) -> None:
        self.model = model
        self.min_interval_s = 60.0 / rpm
        self.max_retries = max_retries
        self.db_path = Path(db_path)
        self._last_call_at: float | None = None

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute(_CREATE_LLM_CALLS)
        # Tablas creadas antes de `context` (N1–N5): se añade la columna, las filas viejas quedan en NULL.
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(llm_calls)")}
        if "context" not in columns:
            self._conn.execute("ALTER TABLE llm_calls ADD COLUMN context TEXT")
        self._conn.commit()

    def _generate(self, system: str, user: str, schema: type[BaseModel]) -> tuple[str, int | None, int | None]:
        raise NotImplementedError

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
        context: dict[str, str] | None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO llm_calls (ts, provider, model, input_tokens, output_tokens, latency_ms, ok, error, context)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                self.provider,
                self.model,
                input_tokens,
                output_tokens,
                latency_ms,
                1 if ok else 0,
                error,
                json.dumps(context, ensure_ascii=False, sort_keys=True) if context is not None else None,
            ),
        )
        self._conn.commit()

    def complete_json(
        self, system: str, user: str, schema: type[T], *, context: dict[str, str] | None = None
    ) -> T:
        """Genera contenido con `system`/`user` y lo valida contra `schema`.

        Reintenta solo ante 429/5xx/timeouts (backoff exponencial). Un
        `LLMOutputError` (JSON inválido o que no cumple el schema) no se
        reintenta. Cada intento, exitoso o no, escribe su propia fila en
        `llm_calls`, con `context` en la columna del mismo nombre.
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
                text, input_tokens, output_tokens = self._generate(system, user, schema)
            except Exception as exc:
                latency_ms = int((time.monotonic() - start) * 1000)
                self._log_call(
                    latency_ms, ok=False, error=str(exc), input_tokens=None, output_tokens=None, context=context
                )
                raise

            latency_ms = int((time.monotonic() - start) * 1000)
            try:
                result = schema.model_validate_json(text)
            except Exception as exc:
                self._log_call(
                    latency_ms,
                    ok=False,
                    error=str(exc),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    context=context,
                )
                raise LLMOutputError(
                    f"Respuesta del LLM inválida contra el schema {schema.__name__}: {exc}. Texto crudo: {text!r}"
                ) from exc

            self._log_call(
                latency_ms,
                ok=True,
                error=None,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                context=context,
            )
            return result

        return _do_call()


class GeminiClient(_LoggedLLMClient):
    """Cliente Gemini; el schema viaja como `response_schema` nativo."""

    provider = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str,
        rpm: int,
        db_path: Path,
        max_retries: int = 5,
        client: Any | None = None,
    ) -> None:
        super().__init__(model, rpm, db_path, max_retries)
        self._client = client if client is not None else genai.Client(api_key=api_key)

    def _generate(self, system: str, user: str, schema: type[BaseModel]) -> tuple[str, int | None, int | None]:
        response = self._client.models.generate_content(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )
        usage = response.usage_metadata
        input_tokens = _to_native_int(usage.prompt_token_count) if usage else None
        output_tokens = _to_native_int(usage.candidates_token_count) if usage else None
        return response.text, input_tokens, output_tokens


class DeepSeekClient(_LoggedLLMClient):
    """Cliente DeepSeek (API compatible con OpenAI) vía httpx directo.

    DeepSeek solo ofrece `response_format={"type": "json_object"}`, sin schema: el
    JSON Schema se añade al prompt de sistema (que así contiene la palabra «json»,
    requisito del modo JSON) y la validación es la misma `model_validate_json`.
    Contenido vacío (la API lo avisa como posible) cae en `LLMOutputError`.

    httpx y no el SDK `openai`: ya es dependencia, `pytest-httpx` lo mockea, y el
    SDK trae reintentos propios que se sumarían a los de tenacity sin quedar en
    `llm_calls`.
    """

    provider = "deepseek"

    def __init__(
        self,
        api_key: str,
        model: str,
        rpm: int,
        db_path: Path,
        max_retries: int = 5,
        base_url: str = "https://api.deepseek.com",
        max_tokens: int = 4096,
        timeout_s: float = 300.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        super().__init__(model, rpm, db_path, max_retries)
        self.max_tokens = max_tokens
        # Timeout largo: bajo carga DeepSeek mantiene la conexión abierta con keep-alives en vez de rechazarla.
        self._http = http_client if http_client is not None else httpx.Client(timeout=timeout_s)
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def _generate(self, system: str, user: str, schema: type[BaseModel]) -> tuple[str, int | None, int | None]:
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        system_with_schema = (
            f"{system}\n\nResponde únicamente con un objeto JSON válido que cumpla este JSON Schema:\n{schema_json}"
        )
        response = self._http.post(
            self._url,
            headers=self._headers,
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_with_schema},
                    {"role": "user", "content": user},
                ],
                "response_format": {"type": "json_object"},
                "max_tokens": self.max_tokens,
                "stream": False,
            },
        )
        if response.is_error:
            # El cuerpo trae el motivo (saldo, parámetro inválido…): va al mensaje, y de ahí a `llm_calls.error`.
            raise httpx.HTTPStatusError(
                f"{response.status_code} {response.reason_phrase}. {response.text[:500]}",
                request=response.request,
                response=response,
            )
        data = response.json()
        usage = data.get("usage") or {}
        text = data["choices"][0]["message"].get("content") or ""
        return text, _to_native_int(usage.get("prompt_tokens")), _to_native_int(usage.get("completion_tokens"))


def make_client(task: str, settings: Settings) -> GeminiClient | DeepSeekClient:
    """Cliente del proveedor de `settings.llm_provider` para `task` ("label" | "synthesis").

    `task` elige el RPM (`llm_rpm_<task>`) y, con Gemini, el modelo (`model_<task>`);
    DeepSeek usa `deepseek_model` para ambas tareas. Registra en `llm_calls` de `db_path`.
    """
    if task not in ("label", "synthesis"):
        raise ValueError(f"task desconocida: {task!r} (esperaba 'label' o 'synthesis')")
    rpm = getattr(settings, f"llm_rpm_{task}")
    if settings.llm_provider == "deepseek":
        assert settings.deepseek_api_key is not None and settings.deepseek_model is not None  # validado en Settings
        return DeepSeekClient(
            api_key=settings.deepseek_api_key.get_secret_value(),
            model=settings.deepseek_model,
            rpm=rpm,
            db_path=settings.db_path,
            max_retries=settings.llm_max_retries,
            base_url=settings.deepseek_base_url,
        )
    return GeminiClient(
        api_key=settings.gemini_api_key.get_secret_value(),
        model=getattr(settings, f"model_{task}"),
        rpm=rpm,
        db_path=settings.db_path,
        max_retries=settings.llm_max_retries,
    )


def _to_native_int(value: Any) -> int | None:
    """Convierte un contador de tokens del SDK a `int` nativo (o `None`)."""
    return int(value) if value is not None else None
