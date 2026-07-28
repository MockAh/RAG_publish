"""Embeddings e5 multilingües: capa única de acceso a `sentence-transformers`.

# ══════════════════════════════════════════════════════════════════════════
# REGLA CRÍTICA (congelada en docs/01-CONTRATOS-DE-DATOS_v11.md, parámetros
# globales, convención de prefijos e5, OBLIGATORIA): toda CONSULTA se embebe
# con el prefijo "query: "; todo DOCUMENTO/chunk con el prefijo "passage: ".
# Sin estos prefijos los espacios vectoriales de consulta y de documento del
# modelo e5 NO son comparables entre sí. Aplica a TODAS las fases del
# proyecto (02 relevancia, 03 indexación/retrieve, 04 clustering).
# ══════════════════════════════════════════════════════════════════════════
"""

from functools import lru_cache
from typing import Any


class Embedder:
    """Envuelve un `SentenceTransformer` e5 aplicando prefijos y floats nativos.

    El modelo se carga de forma lazy (primera llamada a `embed_passages` o
    `embed_query`) y se cachea en la instancia, para que importar este módulo
    sea barato. `encoder` es inyectable (tests): si se pasa, nunca se carga
    el modelo real.
    """

    def __init__(self, model_name: str, encoder: Any | None = None) -> None:
        self.model_name = model_name
        self._encoder = encoder

    def _get_encoder(self) -> Any:
        if self._encoder is None:
            from sentence_transformers import SentenceTransformer

            self._encoder = SentenceTransformer(self.model_name)
        return self._encoder

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        """Embebe documentos/chunks anteponiendo el prefijo "passage: "."""
        encoder = self._get_encoder()
        prefixed = [f"passage: {text}" for text in texts]
        vectors = encoder.encode(prefixed)
        return [_to_native_float_list(vector) for vector in vectors]

    def embed_query(self, text: str) -> list[float]:
        """Embebe una consulta anteponiendo el prefijo "query: "."""
        encoder = self._get_encoder()
        vector = encoder.encode(f"query: {text}")
        return _to_native_float_list(vector)


def _to_native_float_list(vector: Any) -> list[float]:
    """Convierte un vector (lista o `numpy.ndarray`) a `list[float]` nativos.

    Regla F5 (fase 02): nunca dejar que un `np.float32` cruce la frontera
    hacia persistencia (en fase 02 numpy llegó hasta SQLite como BLOB
    silencioso).
    """
    return [float(x) for x in vector]


@lru_cache(maxsize=None)
def get_embedder(model_name: str) -> Embedder:
    """Devuelve un `Embedder` cacheado a nivel de módulo (singleton por modelo).

    Evita cargar el mismo modelo dos veces en la misma corrida.
    """
    return Embedder(model_name)
