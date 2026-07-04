"""Relevancia por similitud coseno con embeddings e5 multilingües (T7).

# ══════════════════════════════════════════════════════════════════════════
# REGLA CRÍTICA (congelada en docs/01-CONTRATOS-DE-DATOS_v11.md, parámetros
# globales): toda CONSULTA se embebe con el prefijo "query: "; todo DOCUMENTO
# (título+abstract) se embebe con el prefijo "passage: ". Sin estos prefijos
# los espacios vectoriales del modelo e5 NO son comparables entre sí.
# Aplica a TODAS las fases del proyecto (02 relevancia, 03 indexación/retrieve,
# 04 clustering).
# ══════════════════════════════════════════════════════════════════════════

El modelo e5 devuelve vectores ya normalizados: el coseno resultante cae en un
rango útil estrecho (~0.6-1.0 en la práctica). El umbral de aceptación se
calibra empíricamente en T13, no aquí.
"""

from excavador.models import PaperRecord


def _cosine_similarity(a, b) -> float:
    """Similitud coseno entre dos vectores (listas o arrays de floats)."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class RelevanceScorer:
    """Puntúa PaperRecord por similitud coseno tema↔abstract con e5.

    El modelo `SentenceTransformer` se carga lazy (primera llamada a `score`),
    para que importar este módulo sea barato. `_encoder` es inyectable: los
    tests lo asignan directamente para no depender del modelo real.
    """

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._encoder = None

    def _get_encoder(self):
        if self._encoder is None:
            from sentence_transformers import SentenceTransformer

            self._encoder = SentenceTransformer(self.model_name)
        return self._encoder

    def score(self, topic: str, records: list[PaperRecord]) -> list[PaperRecord]:
        """Asigna `relevance_score` (coseno recortado a [0,1]) a copias de `records`.

        Embebe `topic` una sola vez con prefijo "query: " y todos los
        `records` en un único batch con prefijo "passage: ". No muta los
        records originales.
        """
        encoder = self._get_encoder()
        query_vector = encoder.encode(f"query: {topic}")

        passages = [f"passage: {record.title}. {record.abstract}" for record in records]
        passage_vectors = encoder.encode(passages)

        scored_records = []
        for record, vector in zip(records, passage_vectors):
            cosine = _cosine_similarity(query_vector, vector)
            clipped = max(0.0, min(1.0, cosine))
            scored_records.append(record.model_copy(update={"relevance_score": clipped}))
        return scored_records

    @staticmethod
    def split_by_threshold(
        records: list[PaperRecord], threshold: float
    ) -> tuple[list[PaperRecord], list[PaperRecord]]:
        """(keep, discard) según `relevance_score >= threshold`, orden estable."""
        keep = [record for record in records if record.relevance_score >= threshold]
        discard = [record for record in records if record.relevance_score < threshold]
        return keep, discard
