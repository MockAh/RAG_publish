"""Almacén vectorial de `Chunk`s (contrato C2) sobre Chroma embebida.

Decisión P1 (`docs/03-REGISTRO-CONSIDERACIONES-BIBLIOTECA_v15.md`): base
vectorial Chroma embebida, cliente persistente. Los embeddings los calcula
siempre `biblioteca.embedder.Embedder`, nunca Chroma: la colección se crea
sin función de embedding automática (nuestro modelo es e5, no el default de
Chroma).

Decisión P6: el payload de cada punto lleva `from_abstract: bool`, que marca
los chunks provenientes de texto tipográficamente degradado (abstract, ver
hallazgo A1), para que el Verificador de fase 05 los identifique. Ese campo
vive solo en el payload de Chroma, NO forma parte de C2.
"""

from __future__ import annotations

import logging
from pathlib import Path

import chromadb

from biblioteca.models import Chunk

logger = logging.getLogger(__name__)


class ChunkStore:
    """Envuelve una colección Chroma persistente de `Chunk`s."""

    def __init__(self, chroma_dir: Path, collection_name: str = "chunks") -> None:
        """Abre (o crea) una colección persistente en `chroma_dir` con métrica coseno."""
        self._client = chromadb.PersistentClient(path=str(chroma_dir))
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            embedding_function=None,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert_chunks(
        self, chunks: list[Chunk], embeddings: list[list[float]], from_abstract: bool = False
    ) -> int:
        """Inserta o actualiza `chunks` con sus `embeddings` (idempotente por `chunk_id`).

        El payload de cada punto lleva todos los campos de C2 (menos `text`,
        que va como documento) más `from_abstract` (P6). Los offsets se
        convierten a `int` nativo y los embeddings a `float` nativo antes de
        escribir (regla F5).
        """
        if len(chunks) != len(embeddings):
            raise ValueError(
                f"chunks ({len(chunks)}) y embeddings ({len(embeddings)}) deben tener la misma longitud"
            )
        if not chunks:
            return 0

        ids = [chunk.chunk_id for chunk in chunks]
        documents = [chunk.text for chunk in chunks]
        metadatas = [
            {
                "paper_id": chunk.paper_id,
                "section": chunk.section,
                "char_start": int(chunk.char_start),
                "char_end": int(chunk.char_end),
                "embedding_model": chunk.embedding_model,
                "from_abstract": from_abstract,
            }
            for chunk in chunks
        ]
        native_embeddings = [[float(x) for x in vector] for vector in embeddings]

        self._collection.upsert(
            ids=ids, embeddings=native_embeddings, documents=documents, metadatas=metadatas
        )
        logger.info("upsert_chunks: %d chunks escritos", len(chunks))
        return len(chunks)

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        """Busca un `Chunk` exacto por `chunk_id`; None si no existe."""
        result = self._collection.get(ids=[chunk_id], include=["documents", "metadatas"])
        ids = result["ids"]
        if not ids:
            return None
        metadata = result["metadatas"][0]
        text = result["documents"][0]
        return Chunk(
            chunk_id=ids[0],
            paper_id=metadata["paper_id"],
            section=metadata["section"],
            text=text,
            char_start=metadata["char_start"],
            char_end=metadata["char_end"],
            embedding_model=metadata["embedding_model"],
        )

    def count(self) -> int:
        """Número total de chunks almacenados."""
        return self._collection.count()

    def has_paper(self, paper_id: str) -> bool:
        """Indica si ya hay chunks indexados de `paper_id`."""
        result = self._collection.get(where={"paper_id": paper_id}, include=[])
        return len(result["ids"]) > 0

    def delete_paper(self, paper_id: str) -> int:
        """Borra todos los chunks de `paper_id`. Devuelve cuántos se borraron."""
        existing = self._collection.get(where={"paper_id": paper_id}, include=[])
        ids = existing["ids"]
        if not ids:
            return 0
        self._collection.delete(ids=ids)
        logger.info("delete_paper: %d chunks borrados de %s", len(ids), paper_id)
        return len(ids)
