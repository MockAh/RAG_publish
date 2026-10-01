"""Tests para expertos.models (contratos C3, C4 y C5)."""

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from expertos.labeling import ClusterLabel
from expertos.models import Claim, ExpertAnswer, Synthesis, SynthesisMap, SynthesisMapEntry

CONTRACTS_PATH = Path(__file__).resolve().parents[2] / "docs" / "01-CONTRATOS-DE-DATOS_v11.md"

# Nombres de campo de C3/C4/C5, en el orden del contrato. Red de seguridad contra
# divergencias con la fase 05: cambiar esta lista exige cambiar el contrato.
EXPECTED_FIELDS: dict[type[BaseModel], list[str]] = {
    Claim: ["text", "supporting_chunks", "stance"],
    Synthesis: ["synthesis_id", "expert_id", "topic_label", "summary", "key_claims", "paper_ids", "updated_at"],
    SynthesisMapEntry: ["expert_id", "topic_label", "one_liner", "n_papers", "keywords"],
    ExpertAnswer: ["expert_id", "question", "answer", "evidence", "confidence", "gaps"],
}

UPDATED_AT = datetime(2026, 10, 1, 12, 30, tzinfo=timezone.utc)


def _words(n: int) -> str:
    """Texto de `n` palabras con acentos y ñ."""
    vocabulary = ["crítica", "economía", "política", "señorío", "año", "ethos", "barroco", "mestizaje"]
    return " ".join(vocabulary[i % len(vocabulary)] for i in range(n))


def _claim(**overrides) -> Claim:
    values = {
        "text": "El ethos barroco es una estrategia de resistencia en la modernidad capitalista.",
        "supporting_chunks": ["openalex:W2140093523#abstract#0", "doi:10.1344/oxi.2013.i2.6382#results#3"],
        "stance": "supports",
        **overrides,
    }
    return Claim(**values)


def _synthesis(**overrides) -> Synthesis:
    values = {
        "synthesis_id": "C3-kmeans-k9-seed42-98b2c308",
        "expert_id": "C3",
        "topic_label": "Ethos barroco, mestizaje cultural y modernidades alternativas",
        "summary": _words(400),
        "key_claims": [_claim(), _claim(text="La señora Ñuñoa reseña el año barroco.", stance="mentions")],
        "paper_ids": ["openalex:W2140093523", "openalex:W2516540948"],
        "updated_at": UPDATED_AT,
        **overrides,
    }
    return Synthesis(**values)


def _entry(**overrides) -> SynthesisMapEntry:
    values = {
        "expert_id": "C3",
        "topic_label": "Ethos barroco, mestizaje cultural y modernidades alternativas",
        "one_liner": "Responde sobre el ethos barroco, el mestizaje cultural y la crítica de la modernidad en América Latina.",
        "n_papers": 17,
        "keywords": ["ethos barroco", "mestizaje", "señorío criollo"],
        **overrides,
    }
    return SynthesisMapEntry(**values)


def _answer(**overrides) -> ExpertAnswer:
    values = {
        "expert_id": "C3",
        "question": "¿Qué relación hay entre ethos barroco y mestizaje según Echeverría?",
        "answer": "El mestizaje cultural es la forma concreta en que el ethos barroco se realizó.",
        "evidence": [_claim()],
        "confidence": "medium",
        "gaps": "Mi corpus no cubre la recepción del concepto en Brasil (año 2020 en adelante).",
        **overrides,
    }
    return ExpertAnswer(**values)


# --- campos 1:1 con el contrato -------------------------------------------------


@pytest.mark.parametrize("model", list(EXPECTED_FIELDS), ids=lambda m: m.__name__)
def test_fields_match_contract_exactly(model: type[BaseModel]) -> None:
    assert list(model.model_fields) == EXPECTED_FIELDS[model]


def _contract_fields(class_name: str) -> list[str]:
    """Nombres de campo de `class_name` leídos del pseudocódigo del documento de contratos."""
    text = CONTRACTS_PATH.read_text(encoding="utf-8")
    match = re.search(rf"^class {class_name}\(BaseModel\):\n((?:    .*\n)+)", text, flags=re.MULTILINE)
    assert match, f"{class_name} no aparece en {CONTRACTS_PATH.name}"
    return re.findall(r"^    (\w+):", match.group(1), flags=re.MULTILINE)


@pytest.mark.parametrize("model", list(EXPECTED_FIELDS), ids=lambda m: m.__name__)
def test_expected_fields_match_contract_document(model: type[BaseModel]) -> None:
    """Si el documento de contratos cambia, este test obliga a revisar los modelos."""
    assert _contract_fields(model.__name__) == EXPECTED_FIELDS[model]


def test_synthesis_map_wraps_literal_c4_entries() -> None:
    """El contenedor es de fase 04; sus entradas son `SynthesisMapEntry` sin cambios."""
    assert list(SynthesisMap.model_fields) == ["run_id", "updated_at", "entries"]
    assert SynthesisMap.model_fields["entries"].annotation == list[SynthesisMapEntry]


# --- round-trip JSON ------------------------------------------------------------


@pytest.mark.parametrize(
    "instance",
    [
        _claim(),
        _synthesis(),
        _entry(),
        SynthesisMap(run_id="kmeans-k9-seed42-98b2c308", updated_at=UPDATED_AT, entries=[_entry(), _entry(expert_id="C4")]),
        _answer(),
        _answer(gaps=None, confidence="low"),
    ],
    ids=["Claim", "Synthesis", "SynthesisMapEntry", "SynthesisMap", "ExpertAnswer", "ExpertAnswer-gaps-None"],
)
def test_json_round_trip_preserves_accents_and_enye(instance: BaseModel) -> None:
    dumped = instance.model_dump_json()

    assert type(instance).model_validate_json(dumped) == instance
    assert "\\u" not in dumped  # acentos y ñ viajan como UTF-8, no escapados
    if not isinstance(instance, Claim):
        assert any(c in dumped for c in "ñáéíóú¿")


def test_round_trip_keeps_timezone_aware_updated_at() -> None:
    restored = Synthesis.model_validate_json(_synthesis().model_dump_json())

    assert restored.updated_at == UPDATED_AT
    assert restored.updated_at.tzinfo is not None


# --- validadores de longitud ----------------------------------------------------


def test_one_liner_of_40_words_passes_and_41_is_rejected() -> None:
    assert _entry(one_liner=_words(40)).one_liner == _words(40)

    with pytest.raises(ValidationError, match="41 palabras"):
        _entry(one_liner=_words(41))


def test_cluster_label_shares_the_one_liner_check() -> None:
    """N5 y C4 aplican la misma regla: una etiqueta que pasa N5 cabe en el mapa."""
    with pytest.raises(ValidationError, match="41 palabras"):
        ClusterLabel(topic_label="x", one_liner=_words(41), keywords=[], coherent=True, note=None)


@pytest.mark.parametrize("n_words", [300, 550, 800])
def test_summary_within_300_800_words_passes(n_words: int) -> None:
    assert len(_synthesis(summary=_words(n_words)).summary.split()) == n_words


@pytest.mark.parametrize("n_words", [0, 299, 801, 900])
def test_summary_outside_300_800_words_is_rejected(n_words: int) -> None:
    with pytest.raises(ValidationError, match=f"{n_words} palabras"):
        _synthesis(summary=_words(n_words))


# --- Claim y literales ----------------------------------------------------------


def test_claim_without_supporting_chunks_is_rejected() -> None:
    """D5: prohibido afirmar sin chunk_id (C3 no autoriza la lista vacía)."""
    with pytest.raises(ValidationError, match="supporting_chunks"):
        _claim(supporting_chunks=[])


def test_claim_without_support_is_rejected_inside_expert_answer() -> None:
    with pytest.raises(ValidationError, match="supporting_chunks"):
        _answer(evidence=[{"text": "afirmación sin fuente", "supporting_chunks": [], "stance": "supports"}])


@pytest.mark.parametrize("stance", ["supports", "contradicts", "mentions"])
def test_stance_accepts_the_three_literals(stance: str) -> None:
    assert _claim(stance=stance).stance == stance


@pytest.mark.parametrize("stance", ["neutral", "Supports", "critica", "", None])
def test_stance_rejects_anything_else(stance: object) -> None:
    with pytest.raises(ValidationError, match="stance"):
        _claim(stance=stance)


@pytest.mark.parametrize("confidence", ["very_high", "alta", 0.9, None])
def test_confidence_rejects_non_literals(confidence: object) -> None:
    """`confidence` es juicio del LLM, nunca un score numérico (L1)."""
    with pytest.raises(ValidationError, match="confidence"):
        _answer(confidence=confidence)


def test_gaps_is_required_but_nullable() -> None:
    """El contrato no da default a `gaps`: el Experto tiene que pronunciarse."""
    values = _answer().model_dump()
    del values["gaps"]

    with pytest.raises(ValidationError, match="gaps"):
        ExpertAnswer(**values)
    assert _answer(gaps=None).gaps is None


def test_synthesis_map_rejects_duplicated_expert_id() -> None:
    with pytest.raises(ValidationError, match="expert_id repetido en el mapa: C3"):
        SynthesisMap(run_id="r", updated_at=UPDATED_AT, entries=[_entry(), _entry(one_liner="otra")])
