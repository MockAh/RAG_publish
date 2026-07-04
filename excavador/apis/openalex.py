"""Cliente de OpenAlex: normalizador canónico de todo el pipeline (A2).

Todos los requests incluyen el parámetro `mailto` (polite pool de OpenAlex).
"""

import httpx

from excavador.apis.base import ApiClient
from excavador.models import RawHit

SELECT_FIELDS = (
    "id,doi,title,display_name,authorships,publication_year,primary_location,"
    "abstract_inverted_index,type,referenced_works,open_access,best_oa_location"
)

_BATCH_SIZE = 50


def invert_abstract(inverted_index: dict | None) -> str:
    """Reconstruye el abstract desde el índice invertido de OpenAlex.

    `inverted_index` mapea palabra -> lista de posiciones. Devuelve "" si el
    índice es None o está vacío.
    """
    if not inverted_index:
        return ""
    positions: dict[int, str] = {}
    for word, idxs in inverted_index.items():
        for idx in idxs:
            positions[idx] = word
    return " ".join(positions[i] for i in sorted(positions))


class OpenAlexClient(ApiClient):
    """Cliente de la API de OpenAlex (columna vertebral, A1/A2)."""

    source_api = "openalex"
    min_interval_s = 0.15

    BASE_URL = "https://api.openalex.org"

    def __init__(self, mailto: str) -> None:
        super().__init__()
        self.mailto = mailto

    @staticmethod
    def _short_id(url_or_id: str) -> str:
        """Extrae el id corto (ej. `W2741809807`) de una URL de OpenAlex."""
        return url_or_id.rsplit("/", 1)[-1]

    def _to_raw_hit(self, work: dict) -> RawHit:
        doi = work.get("doi")
        if doi:
            doi = doi.removeprefix("https://doi.org/")
        return RawHit(
            source_api="openalex",
            raw=work,
            doi=doi,
            title=work.get("display_name"),
            external_id=self._short_id(work.get("id", "")),
        )

    def _paginated_works(self, extra_params: dict, max_results: int) -> list[RawHit]:
        hits: list[RawHit] = []
        cursor: str | None = "*"
        while cursor and len(hits) < max_results:
            params = {
                **extra_params,
                "cursor": cursor,
                "per-page": 200,
                "select": SELECT_FIELDS,
                "mailto": self.mailto,
            }
            data = self._get(f"{self.BASE_URL}/works", params)
            for work in data.get("results", []):
                hits.append(self._to_raw_hit(work))
                if len(hits) >= max_results:
                    break
            cursor = data.get("meta", {}).get("next_cursor")
        return hits[:max_results]

    def search(self, query: str, max_results: int = 50) -> list[RawHit]:
        """Búsqueda semántica de `query`, paginada hasta `max_results`."""
        return self._paginated_works({"search": query}, max_results)

    def search_exact_phrase(self, phrase: str, max_results: int = 200) -> list[RawHit]:
        """Búsqueda por coincidencia exacta de `phrase` en título/abstract (A3)."""
        return self._paginated_works(
            {"filter": f'title_and_abstract.search:"{phrase}"'}, max_results
        )

    def enrich(self, doi: str) -> RawHit | None:
        """Enriquece un work por DOI. Devuelve None si OpenAlex responde 404."""
        params = {"select": SELECT_FIELDS, "mailto": self.mailto}
        try:
            data = self._get(f"{self.BASE_URL}/works/doi:{doi}", params)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        return self._to_raw_hit(data)

    def get_references(self, openalex_id: str) -> list[str]:
        """Ids cortos de OpenAlex referenciados por `openalex_id`."""
        params = {"select": "referenced_works", "mailto": self.mailto}
        data = self._get(f"{self.BASE_URL}/works/{openalex_id}", params)
        return [self._short_id(url) for url in data.get("referenced_works", [])]

    def get_citing(self, openalex_id: str, max_results: int = 100) -> list[RawHit]:
        """Works que citan a `openalex_id` (snowballing hacia adelante, A4)."""
        return self._paginated_works({"filter": f"cites:{openalex_id}"}, max_results)

    def enrich_batch(self, openalex_ids: list[str]) -> list[RawHit]:
        """Enriquece varios ids de OpenAlex en lote (máx. 50 ids por request)."""
        hits: list[RawHit] = []
        for i in range(0, len(openalex_ids), _BATCH_SIZE):
            group = openalex_ids[i : i + _BATCH_SIZE]
            params = {
                "filter": f"openalex_id:{'|'.join(group)}",
                "per-page": 200,
                "select": SELECT_FIELDS,
                "mailto": self.mailto,
            }
            data = self._get(f"{self.BASE_URL}/works", params)
            hits.extend(self._to_raw_hit(work) for work in data.get("results", []))
        return hits
