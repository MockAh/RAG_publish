"""Stub del cliente de PubMed: no implementado en v1 (dominio humanidades)."""

from excavador.apis.base import ApiClient
from excavador.models import RawHit


class PubmedClient(ApiClient):
    """Stub: PubMed no aplica al dominio de humanidades del v1."""

    source_api = "pubmed"
    min_interval_s = 3.0

    def search(self, query: str, max_results: int = 50) -> list[RawHit]:
        raise NotImplementedError("No implementado en v1: dominio humanidades en español")
