"""Stub del cliente de arXiv: no implementado en v1 (dominio humanidades)."""

from excavador.apis.base import ApiClient
from excavador.models import RawHit


class ArxivClient(ApiClient):
    """Stub: arXiv no aplica al dominio de humanidades del v1."""

    source_api = "arxiv"
    min_interval_s = 3.0

    def search(self, query: str, max_results: int = 50) -> list[RawHit]:
        raise NotImplementedError("No implementado en v1: dominio humanidades en español")
