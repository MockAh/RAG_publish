"""Cliente de Semantic Scholar (A1: última prioridad tras OpenAlex/Crossref).

El header ``x-api-key`` solo se incluye si se provee una key: la API funciona
sin ella, con límites de tasa más estrictos.
"""

from excavador.apis.base import ApiClient
from excavador.models import RawHit

FIELDS = (
    "externalIds,title,abstract,year,venue,authors,references.paperId,"
    "openAccessPdf,publicationTypes"
)


class SemanticScholarClient(ApiClient):
    """Cliente de la API de Semantic Scholar."""

    source_api = "semanticscholar"
    min_interval_s = 1.1

    BASE_URL = "https://api.semanticscholar.org"

    def __init__(self, api_key: str | None = None) -> None:
        super().__init__()
        self.api_key = api_key
        if api_key is not None:
            self._client.headers["x-api-key"] = api_key

    def _to_raw_hit(self, paper: dict) -> RawHit:
        doi = (paper.get("externalIds") or {}).get("DOI")
        if doi:
            doi = doi.lower()
        return RawHit(
            source_api="semanticscholar",
            raw=paper,
            doi=doi,
            title=paper.get("title"),
            external_id=paper.get("paperId", ""),
        )

    def search(self, query: str, max_results: int = 50) -> list[RawHit]:
        """Búsqueda de `query`, paginada con `offset` si `max_results` > 100."""
        limit = min(max_results, 100)
        hits: list[RawHit] = []
        offset = 0
        while len(hits) < max_results:
            params = {
                "query": query,
                "fields": FIELDS,
                "limit": min(limit, max_results - len(hits)),
                "offset": offset,
            }
            data = self._get(f"{self.BASE_URL}/graph/v1/paper/search", params)
            papers = data.get("data", [])
            if not papers:
                break
            hits.extend(self._to_raw_hit(paper) for paper in papers)
            offset += len(papers)
            if data.get("next") is None:
                break
        return hits[:max_results]

    def get_references(self, paper_id: str) -> list[str]:
        """Ids de los papers referenciados por `paper_id`.

        Ignora las entradas cuyo `citedPaper` venga None (S2 tiene
        referencias sin resolver).
        """
        params = {"fields": "paperId", "limit": 100}
        data = self._get(f"{self.BASE_URL}/graph/v1/paper/{paper_id}/references", params)
        return [
            ref["citedPaper"]["paperId"]
            for ref in data.get("data", [])
            if ref.get("citedPaper") and ref["citedPaper"].get("paperId")
        ]
