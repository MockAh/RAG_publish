"""Cliente de Crossref (A1: prioridad tras OpenAlex).

El polite pool de Crossref se activa vía el header ``User-Agent`` (no un
parámetro de query, a diferencia de OpenAlex): se incluye el `mailto` en todos
los requests con el formato ``excavador/0.1 (mailto:<email>)``.
"""

import httpx

from excavador.apis.base import ApiClient
from excavador.models import RawHit


class CrossrefClient(ApiClient):
    """Cliente de la API de Crossref."""

    source_api = "crossref"
    min_interval_s = 1.0

    BASE_URL = "https://api.crossref.org"

    def __init__(self, mailto: str) -> None:
        super().__init__()
        self.mailto = mailto
        self._client.headers["User-Agent"] = f"excavador/0.1 (mailto:{mailto})"

    def _to_raw_hit(self, item: dict) -> RawHit:
        doi = item.get("DOI")
        if doi:
            doi = doi.lower()
        titles = item.get("title") or []
        title = titles[0] if titles else None
        return RawHit(
            source_api="crossref",
            raw=item,
            doi=doi,
            title=title,
            external_id=doi or "",
        )

    def search(self, query: str, max_results: int = 50) -> list[RawHit]:
        """Búsqueda de `query`, paginada con `offset` si `max_results` > 100."""
        rows = min(max_results, 100)
        hits: list[RawHit] = []
        offset = 0
        while len(hits) < max_results:
            params = {"query": query, "rows": rows, "offset": offset}
            data = self._get(f"{self.BASE_URL}/works", params)
            items = data.get("message", {}).get("items", [])
            if not items:
                break
            hits.extend(self._to_raw_hit(item) for item in items)
            offset += len(items)
            if len(items) < rows:
                break
        return hits[:max_results]

    def enrich(self, doi: str) -> RawHit | None:
        """Enriquece un work por DOI. Devuelve None si Crossref responde 404."""
        try:
            data = self._get(f"{self.BASE_URL}/works/{doi}", {})
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        return self._to_raw_hit(data.get("message", {}))
