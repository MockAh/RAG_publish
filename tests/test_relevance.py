"""Tests para excavador.relevance.RelevanceScorer."""

from datetime import datetime, timezone

import pytest

from excavador.models import PaperRecord
from excavador.relevance import RelevanceScorer


def _record(**overrides) -> PaperRecord:
    base = dict(
        paper_id="openalex:W1",
        doi=None,
        title="Un título cualquiera",
        authors=["Autor Uno"],
        year=2020,
        venue=None,
        abstract="",
        source_api="openalex",
        work_type="article",
        pdf_path=None,
        relevance_score=0.0,
        references_ids=[],
        ingested_at=datetime.now(timezone.utc),
    )
    base.update(overrides)
    return PaperRecord(**base)


class _DummyEncoder:
    """Encoder inyectable: devuelve vectores fijos según el texto de entrada."""

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self.vectors = vectors
        self.calls: list = []

    def encode(self, texts):
        self.calls.append(texts)
        if isinstance(texts, str):
            return self.vectors[texts]
        return [self.vectors[text] for text in texts]


def _scorer_with_encoder(encoder: _DummyEncoder) -> RelevanceScorer:
    scorer = RelevanceScorer("dummy-model")
    scorer._encoder = encoder
    return scorer


def test_score_sends_exact_query_and_passage_prefixes_to_encoder() -> None:
    r1 = _record(title="T1", abstract="A1")
    r2 = _record(title="T2", abstract="A2")
    encoder = _DummyEncoder(
        {
            "query: cultura y capitalismo": [1.0, 0.0],
            "passage: T1. A1": [1.0, 0.0],
            "passage: T2. A2": [0.0, 1.0],
        }
    )
    scorer = _scorer_with_encoder(encoder)

    scorer.score("cultura y capitalismo", [r1, r2])

    assert encoder.calls[0] == "query: cultura y capitalismo"
    assert encoder.calls[1] == ["passage: T1. A1", "passage: T2. A2"]


def test_score_produces_expected_order_from_handcrafted_vectors() -> None:
    r_high = _record(title="Alto", abstract="")
    r_mid = _record(title="Medio", abstract="")
    r_low = _record(title="Bajo", abstract="")
    encoder = _DummyEncoder(
        {
            "query: tema": [1.0, 0.0],
            "passage: Alto. ": [1.0, 0.0],
            "passage: Medio. ": [0.7, 0.7],
            "passage: Bajo. ": [0.0, 1.0],
        }
    )
    scorer = _scorer_with_encoder(encoder)

    scored = scorer.score("tema", [r_high, r_mid, r_low])

    high, mid, low = (r.relevance_score for r in scored)
    assert high > mid > low
    assert high == 1.0
    assert low == 0.0


def test_negative_cosine_is_clipped_to_zero() -> None:
    r = _record(title="Opuesto", abstract="")
    encoder = _DummyEncoder(
        {
            "query: tema": [1.0, 0.0],
            "passage: Opuesto. ": [-1.0, 0.0],
        }
    )
    scorer = _scorer_with_encoder(encoder)

    scored = scorer.score("tema", [r])

    assert scored[0].relevance_score == 0.0


def test_split_by_threshold_keeps_order_and_partitions_correctly() -> None:
    r1 = _record(paper_id="p1", relevance_score=0.9)
    r2 = _record(paper_id="p2", relevance_score=0.5)
    r3 = _record(paper_id="p3", relevance_score=0.2)

    keep, discard = RelevanceScorer.split_by_threshold([r1, r2, r3], threshold=0.5)

    assert keep == [r1, r2]
    assert discard == [r3]


def test_score_does_not_mutate_original_records() -> None:
    r = _record(title="Original", abstract="", relevance_score=0.0)
    encoder = _DummyEncoder(
        {
            "query: tema": [1.0, 0.0],
            "passage: Original. ": [1.0, 0.0],
        }
    )
    scorer = _scorer_with_encoder(encoder)

    scored = scorer.score("tema", [r])

    assert r.relevance_score == 0.0
    assert scored[0] is not r
    assert scored[0].relevance_score == 1.0


@pytest.mark.slow
def test_real_model_scores_spanish_topic_higher_for_related_english_abstract() -> None:
    """Usa el modelo real e5 multilingüe: papers en español pueden tener
    abstracts en inglés (hallazgo A2); e5 es multilingüe y debe puntuar
    más alto el abstract relacionado aunque esté en otro idioma que el tema.
    """
    topic = "recepción crítica de Bolívar Echeverría, filosofía de la cultura"

    related = _record(
        title="Baroque modernity and use value in Latin American thought",
        abstract=(
            "This article examines the concept of baroque modernity as developed "
            "by Bolívar Echeverría, discussing use value, culture, and capitalism "
            "in the context of Latin American critical theory."
        ),
    )
    unrelated = _record(
        title="Synthesis of novel organic compounds via catalytic coupling",
        abstract=(
            "We report the synthesis of several novel organic compounds using "
            "palladium-catalyzed cross-coupling reactions, characterized by NMR "
            "and mass spectrometry."
        ),
    )

    scorer = RelevanceScorer("intfloat/multilingual-e5-large")
    scored = scorer.score(topic, [related, unrelated])

    related_score, unrelated_score = scored[0].relevance_score, scored[1].relevance_score
    print(f"related_score={related_score} unrelated_score={unrelated_score}")

    assert related_score > unrelated_score
