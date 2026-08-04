"""Tests para biblioteca.store.ChunkStore."""

from pathlib import Path

import pytest

from biblioteca.embedder import Embedder
from biblioteca.models import Chunk
from biblioteca.store import ChunkStore

_DIM = 8


def _vector(seed: float) -> list[float]:
    return [seed + i * 0.01 for i in range(_DIM)]


def _vec2(x: float, y: float) -> list[float]:
    """Vector de dimensión `_DIM` con solo las 2 primeras componentes no nulas.

    Facilita calcular a mano la similitud coseno esperada: `cos = x / sqrt(x^2 + y^2)`
    frente a la consulta `_vec2(1, 0)`.
    """
    return [x, y] + [0.0] * (_DIM - 2)


class _FakeEncoder:
    """Encoder inyectable: registra el texto recibido y devuelve un vector fijo."""

    def __init__(self, vector: list[float]) -> None:
        self.vector = vector
        self.calls: list[str] = []

    def encode(self, text: str) -> list[float]:
        self.calls.append(text)
        return self.vector


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


def _make_chunk_section(paper_id: str, section: str, seq: int, text: str = "texto de prueba") -> Chunk:
    return Chunk(
        chunk_id=Chunk.build_id(paper_id, section, seq),
        paper_id=paper_id,
        section=section,
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


# --- Tests de ChunkStore.retrieve ---
#
# Se usa `_vec2(x, y)` (resto de componentes a 0) frente a la consulta
# `_vec2(1, 0)`: la similitud coseno esperada es `x / sqrt(x^2 + y^2)`, lo que
# permite calcular a mano el orden esperado.
#
# Dataset compartido (5 chunks, cos frente a la consulta entre paréntesis):
#   A = p1/introduction  _vec2(1, 0)  -> cos = 1.0
#   B = p1/results       _vec2(2, 1)  -> cos = 0.8944...
#   C = p2/introduction  _vec2(1, 1)  -> cos = 0.7071...
#   D = p2/results       _vec2(1, 2)  -> cos = 0.4472...
#   E = p3/methods       _vec2(0, 1)  -> cos = 0.0


def _build_dataset_store(tmp_path: Path) -> tuple[ChunkStore, dict[str, Chunk]]:
    store = ChunkStore(tmp_path)
    chunks = {
        "A": _make_chunk_section("p1", "introduction", 0),
        "B": _make_chunk_section("p1", "results", 0),
        "C": _make_chunk_section("p2", "introduction", 0),
        "D": _make_chunk_section("p2", "results", 0),
        "E": _make_chunk_section("p3", "methods", 0),
    }
    vectors = {
        "A": _vec2(1, 0),
        "B": _vec2(2, 1),
        "C": _vec2(1, 1),
        "D": _vec2(1, 2),
        "E": _vec2(0, 1),
    }
    store.upsert_chunks(list(chunks.values()), [vectors[k] for k in chunks])
    return store, chunks


def _query_embedder() -> tuple[Embedder, _FakeEncoder]:
    encoder = _FakeEncoder(_vec2(1, 0))
    return Embedder("dummy-model", encoder=encoder), encoder


def test_retrieve_sin_filtros_ordena_por_score_descendente(tmp_path: Path) -> None:
    store, chunks = _build_dataset_store(tmp_path)
    embedder, _ = _query_embedder()

    results = store.retrieve("mi consulta", top_k=3, embedder=embedder)

    assert [r.chunk.chunk_id for r in results] == [
        chunks["A"].chunk_id,
        chunks["B"].chunk_id,
        chunks["C"].chunk_id,
    ]
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_retrieve_top_k_mayor_que_existentes_devuelve_todos_sin_error(tmp_path: Path) -> None:
    store = ChunkStore(tmp_path)
    chunk_a = _make_chunk_section("p1", "introduction", 0)
    chunk_b = _make_chunk_section("p1", "results", 0)
    store.upsert_chunks([chunk_a, chunk_b], [_vec2(1, 0), _vec2(2, 1)])
    embedder, _ = _query_embedder()

    results = store.retrieve("mi consulta", top_k=10, embedder=embedder)

    assert len(results) == 2
    assert [r.chunk.chunk_id for r in results] == [chunk_a.chunk_id, chunk_b.chunk_id]


def test_retrieve_filtro_paper_ids_restringe_al_paper(tmp_path: Path) -> None:
    store, chunks = _build_dataset_store(tmp_path)
    embedder, _ = _query_embedder()

    results = store.retrieve("q", top_k=10, filter_paper_ids=["p1"], embedder=embedder)

    assert [r.chunk.chunk_id for r in results] == [chunks["A"].chunk_id, chunks["B"].chunk_id]
    assert all(r.chunk.paper_id == "p1" for r in results)


def test_retrieve_filtro_sections_restringe_a_esas_secciones(tmp_path: Path) -> None:
    store, chunks = _build_dataset_store(tmp_path)
    embedder, _ = _query_embedder()

    results = store.retrieve("q", top_k=10, filter_sections=["introduction"], embedder=embedder)

    assert [r.chunk.chunk_id for r in results] == [chunks["A"].chunk_id, chunks["C"].chunk_id]
    assert all(r.chunk.section == "introduction" for r in results)


def test_retrieve_filtros_combinados(tmp_path: Path) -> None:
    store, chunks = _build_dataset_store(tmp_path)
    embedder, _ = _query_embedder()

    results = store.retrieve(
        "q", top_k=10, filter_paper_ids=["p2"], filter_sections=["results"], embedder=embedder
    )

    assert [r.chunk.chunk_id for r in results] == [chunks["D"].chunk_id]


def test_retrieve_filtro_sin_coincidencias_devuelve_lista_vacia(tmp_path: Path) -> None:
    store, _ = _build_dataset_store(tmp_path)
    embedder, _ = _query_embedder()

    results = store.retrieve("q", filter_paper_ids=["no-existe"], embedder=embedder)

    assert results == []


def test_retrieve_coleccion_vacia_devuelve_lista_vacia(tmp_path: Path) -> None:
    store = ChunkStore(tmp_path)

    assert store.retrieve("q") == []


def test_retrieve_antepone_prefijo_query(tmp_path: Path) -> None:
    store = ChunkStore(tmp_path)
    chunk = _make_chunk_section("p1", "introduction", 0)
    store.upsert_chunks([chunk], [_vec2(1, 0)])
    embedder, encoder = _query_embedder()

    store.retrieve("mi pregunta de prueba", embedder=embedder)

    assert len(encoder.calls) == 1
    assert encoder.calls[0].startswith("query: ")
    assert encoder.calls[0] == "query: mi pregunta de prueba"


def test_retrieve_scores_en_rango_y_conserva_from_abstract_y_campos_c2(tmp_path: Path) -> None:
    store = ChunkStore(tmp_path)
    chunk = _make_chunk_section("p1", "introduction", 0, "texto del abstract degradado")
    store.upsert_chunks([chunk], [_vec2(1, 0)], from_abstract=True)
    embedder, _ = _query_embedder()

    results = store.retrieve("q", embedder=embedder)

    assert len(results) == 1
    scored = results[0]
    assert 0.0 <= scored.score <= 1.0
    assert scored.from_abstract is True
    assert scored.chunk == chunk

