"""Cliente base abstracto para APIs de búsqueda bibliográfica.

Provee rate limiting (mínimo intervalo entre requests) y reintentos con
`tenacity` sobre un `httpx.Client` compartido por instancia.
"""

import time
from abc import ABC, abstractmethod

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from excavador.models import RawHit


def _is_retryable(exc: BaseException) -> bool:
    """Solo se reintenta en 429, 5xx o timeouts de httpx."""
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or status >= 500
    return False


class ApiClient(ABC):
    """Cliente abstracto de una API de búsqueda bibliográfica."""

    source_api: str
    min_interval_s: float = 1.0

    def __init__(self) -> None:
        self._client = httpx.Client(timeout=30)
        self._last_request_at: float | None = None

    @abstractmethod
    def search(self, query: str, max_results: int = 50) -> list[RawHit]:
        """Busca `query` y devuelve como máximo `max_results` RawHit."""
        raise NotImplementedError

    def _sleep(self, seconds: float) -> None:
        """Duerme `seconds`. Aislado en un método para poder parchearlo en tests."""
        time.sleep(seconds)

    def _apply_rate_limit(self) -> None:
        """Duerme lo necesario para respetar `min_interval_s` entre requests."""
        now = time.monotonic()
        if self._last_request_at is not None:
            elapsed = now - self._last_request_at
            remaining = self.min_interval_s - elapsed
            if remaining > 0:
                self._sleep(remaining)
        self._last_request_at = time.monotonic()

    def _get(self, url: str, params: dict) -> dict:
        """GET con rate limit y reintentos (3 intentos, backoff exponencial).

        Reintenta solo en 429/5xx/timeouts; cualquier otro 4xx levanta
        `httpx.HTTPStatusError` de inmediato.
        """

        @retry(
            reraise=True,
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1),
            retry=retry_if_exception(_is_retryable),
            sleep=self._sleep,
        )
        def _do_request() -> dict:
            self._apply_rate_limit()
            response = self._client.get(url, params=params)
            if response.status_code == 429 or response.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"Status reintentable: {response.status_code}",
                    request=response.request,
                    response=response,
                )
            response.raise_for_status()
            return response.json()

        return _do_request()
