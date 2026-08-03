"""Tests para biblioteca.store.ChunkStore."""

from pathlib import Path

import pytest

from biblioteca.models import Chunk
from biblioteca.store import ChunkStore

_DIM = 8


def _vector(seed: float) -> list[float]:
    return [seed + i * 0.01 for i in range(_DIM)]


def _make_chunk(paper_id: str, seq: int, text: str = "texto de prueba") -> Chunk:
    return Chunk(
        chunk_id=Chunk.build_id(paper_id, "introduction", seq),
        paper_id=paper_id,
        section="introduction",
        text=text,
        char_start=seq * 10,
        char_end=seq * 10 + len(text),
        embedding_model="intfloat/multilingual-e5-large",
    )


def test_roundtrip_preserva_texto_y_campos_c2(tmp_path: Path) -> None:
    store = ChunkStore(tmp_path)
    chunks = [
        _make_chunk("p1", 0, "El niño comió piñón con café en Bogotá."),
        _make_chunk("p1", 1, "La investigación señaló características únicas."),
        _make_chunk("p1", 2, "Tercer chunk sin acentos."),
    ]
    embeddings = [_vector(0.1), _vector(0.2), _vector(0.3)]

    store.upsert_chunks(chunks, embeddings)

    for original in chunks:
        recovered = store.get_chunk(original.chunk_id)
        assert recovered is not None
        assert recovered.chunk_id == original.chunk_id
        assert recovered.paper_id == original.paper_id
        assert recovered.section == original.section
        assert recovered.text == original.text
        assert recovered.char_start == original.char_start
        assert recovered.char_end == original.char_end
        assert recovered.embedding_model == original.embedding_model


def test_upsert_es_idempotente_por_chunk_id(tmp_path: Path) -> None:
    store = ChunkStore(tmp_path)
    chunks = [_make_chunk("p1", 0), _make_chunk("p1", 1)]
    embeddings = [_vector(0.1), _vector(0.2)]

    store.upsert_chunks(chunks, embeddings)
    assert store.count() == 2

    store.upsert_chunks(chunks, embeddings)
    assert store.count() == 2

    updated = [_make_chunk("p1", 0, text="texto actualizado tras reindexar"), chunks[1]]
    store.upsert_chunks(updated, embeddings)
    assert store.count() == 2
    assert store.get_chunk(chunks[0].chunk_id).text == "texto actualizado tras reindexar"


def test_get_chunk_inexistente_devuelve_none(tmp_path: Path) -> None:
    store = ChunkStore(tmp_path)

    assert store.get_chunk("no-existe#introduction#0") is None


@pytest.mark.parametrize("from_abstract", [True, False])
def test_from_abstract_se_persiste_y_recupera(tmp_path: Path, from_abstract: bool) -> None:
    store = ChunkStore(tmp_path)
    chunk = _make_chunk("p1", 0)

    store.upsert_chunks([chunk], [_vector(0.1)], from_abstract=from_abstract)

    result = store._collection.get(ids=[chunk.chunk_id], include=["metadatas"])
    assert result["metadatas"][0]["from_abstract"] is from_abstract


def test_has_paper_y_delete_paper_no_afectan_otros_papers(tmp_path: Path) -> None:
    store = ChunkStore(tmp_path)
    chunks_p1 = [_make_chunk("p1", 0), _make_chunk("p1", 1)]
    chunks_p2 = [_make_chunk("p2", 0)]
    store.upsert_chunks(chunks_p1, [_vector(0.1), _vector(0.2)])
    store.upsert_chunks(chunks_p2, [_vector(0.3)])

    assert store.has_paper("p1") is True
    assert store.has_paper("p2") is True
    assert store.has_paper("p3") is False

    deleted = store.delete_paper("p1")

    assert deleted == 2
    assert store.has_paper("p1") is False
    assert store.has_paper("p2") is True
    assert store.count() == 1
    assert store.get_chunk(chunks_p2[0].chunk_id) is not None


def test_upsert_lanza_valueerror_si_longitudes_no_coinciden(tmp_path: Path) -> None:
    store = ChunkStore(tmp_path)
    chunks = [_make_chunk("p1", 0), _make_chunk("p1", 1)]

    with pytest.raises(ValueError):
        store.upsert_chunks(chunks, [_vector(0.1)])


def test_persistencia_real_sobrevive_a_nueva_instancia(tmp_path: Path) -> None:
    chunk = _make_chunk("p1", 0, "contenido persistente")

    store1 = ChunkStore(tmp_path)
    store1.upsert_chunks([chunk], [_vector(0.1)])
    del store1

    store2 = ChunkStore(tmp_path)
    recovered = store2.get_chunk(chunk.chunk_id)

    assert recovered is not None
    assert recovered.text == "contenido persistente"
    assert store2.count() == 1
