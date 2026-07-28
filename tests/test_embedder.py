"""Tests para biblioteca.embedder.Embedder y get_embedder."""

from typing import Any

import pytest

from biblioteca.embedder import Embedder, get_embedder


class _FakeEncoder:
    """Encoder inyectable: devuelve vectores fijos según el texto de entrada."""

    def __init__(self, vectors: dict[str, Any]) -> None:
        self.vectors = vectors
        self.calls: list = []

    def encode(self, texts: Any) -> Any:
        self.calls.append(texts)
        if isinstance(texts, str):
            return self.vectors[texts]
        return [self.vectors[text] for text in texts]


def test_embed_passages_applies_exact_passage_prefix() -> None:
    encoder = _FakeEncoder(
        {
            "passage: doc uno": [1.0, 0.0],
            "passage: doc dos": [0.0, 1.0],
        }
    )
    embedder = Embedder("dummy-model", encoder=encoder)

    embedder.embed_passages(["doc uno", "doc dos"])

    assert encoder.calls == [["passage: doc uno", "passage: doc dos"]]


def test_embed_query_applies_exact_query_prefix() -> None:
    encoder = _FakeEncoder({"query: cultura": [1.0, 0.0]})
    embedder = Embedder("dummy-model", encoder=encoder)

    embedder.embed_query("cultura")

    assert encoder.calls == ["query: cultura"]


def test_embed_passages_returns_list_of_list_of_native_floats() -> None:
    encoder = _FakeEncoder({"passage: a": [1.0, 2.0], "passage: b": [3.0, 4.0]})
    embedder = Embedder("dummy-model", encoder=encoder)

    result = embedder.embed_passages(["a", "b"])

    assert result == [[1.0, 2.0], [3.0, 4.0]]
    assert all(type(x) is float for vector in result for x in vector)


def test_embed_query_returns_list_of_native_floats() -> None:
    encoder = _FakeEncoder({"query: cultura": [1.0, 0.0]})
    embedder = Embedder("dummy-model", encoder=encoder)

    result = embedder.embed_query("cultura")

    assert result == [1.0, 0.0]
    assert all(type(x) is float for x in result)


def test_embed_passages_converts_numpy_vectors_to_native_floats() -> None:
    """Regresión F5: el encoder real devuelve numpy; sin conversión un
    np.float32 llegaría intacto hasta la persistencia."""
    import numpy as np

    encoder = _FakeEncoder({"passage: a": np.array([1.0, 2.0], dtype=np.float32)})
    embedder = Embedder("dummy-model", encoder=encoder)

    result = embedder.embed_passages(["a"])

    assert result == [[1.0, 2.0]]
    assert type(result[0][0]) is float


def test_embed_query_converts_numpy_vector_to_native_floats() -> None:
    import numpy as np

    encoder = _FakeEncoder({"query: cultura": np.array([1.0, 0.0], dtype=np.float32)})
    embedder = Embedder("dummy-model", encoder=encoder)

    result = embedder.embed_query("cultura")

    assert result == [1.0, 0.0]
    assert type(result[0]) is float


def test_get_embedder_returns_same_instance_for_same_model_name() -> None:
    first = get_embedder("intfloat/multilingual-e5-large")
    second = get_embedder("intfloat/multilingual-e5-large")

    assert first is second


def test_get_embedder_returns_different_instances_for_different_model_names() -> None:
    first = get_embedder("model-a")
    second = get_embedder("model-b")

    assert first is not second


@pytest.mark.slow
def test_real_model_embed_query_has_1024_dims_and_scores_related_passage_higher() -> None:
    """Usa el modelo real e5 multilingüe: 1024 dims y coseno más alto para
    un pasaje afín que para uno ajeno."""
    embedder = get_embedder("intfloat/multilingual-e5-large")

    query_vector = embedder.embed_query("cultura")
    assert len(query_vector) == 1024

    related, unrelated = embedder.embed_passages(
        [
            "La cultura y la sociedad están profundamente entrelazadas en la teoría crítica.",
            "Síntesis de nuevos compuestos orgánicos mediante catálisis de paladio.",
        ]
    )

    def cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(y * y for y in b) ** 0.5
        return dot / (norm_a * norm_b)

    sim_related = cosine(query_vector, related)
    sim_unrelated = cosine(query_vector, unrelated)

    assert sim_related > sim_unrelated
