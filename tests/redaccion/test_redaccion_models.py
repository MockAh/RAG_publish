"""Tests para redaccion.models (contratos C6 y C7; registro por pieza de Y7)."""

import json
import re
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from redaccion.models import (
    ChunkVerdict,
    CitationFailure,
    DraftSection,
    PieceLog,
    PieceRecord,
    VerificationReport,
)

CONTRACTS_PATH = Path(__file__).resolve().parents[2] / "docs" / "01-CONTRATOS-DE-DATOS_v11.md"

# Nombres de campo de C6/C7, en el orden del contrato. Cambiar esta lista exige cambiar el contrato.
EXPECTED_FIELDS: dict[type[BaseModel], list[str]] = {
    DraftSection: ["text", "citations", "unsupported_marked"],
    VerificationReport: ["passed", "failures"],
    CitationFailure: ["sentence", "chunk_id", "reason"],
}

CHUNK_A = "doi:10.37819/humanrev.v9i2.866#Conclusiones#43"
CHUNK_B = "openalex:W2140093523#abstract#0"


def _draft(**overrides) -> DraftSection:
    values = {
        "text": "Según Echeverría, el ethos barroco es una estrategia de resistencia [1]. "
        "La señora Ñuñoa lo discute en el año 2006 [2].",
        "citations": {1: [CHUNK_A], 2: [CHUNK_B, CHUNK_A]},
        "unsupported_marked": True,
        **overrides,
    }
    return DraftSection(**values)


def _failure(**overrides) -> CitationFailure:
    values = {"sentence": "El ethos barroco es universal [1].", "chunk_id": CHUNK_A, "reason": "scope_mismatch", **overrides}
    return CitationFailure(**values)


def _piece(**overrides) -> PieceRecord:
    values = {
        "index": 0,
        "cycle": 1,
        "text": "Según Echeverría, el ethos barroco es una estrategia de resistencia [1].",
        "kind": "factual",
        "pair_role": None,
        "chunk_ids": [CHUNK_A],
        "verdicts": [ChunkVerdict(chunk_id=CHUNK_A, verdict="ok", reason="El pasaje lo afirma con esas palabras.")],
        "status": "verified",
        **overrides,
    }
    return PieceRecord(**values)


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


def test_failure_reason_literals_match_contract_document() -> None:
    text = CONTRACTS_PATH.read_text(encoding="utf-8")
    match = re.search(r"reason: Literal\[(.*)\]", text)
    assert match
    contract = re.findall(r'"(\w+)"', match.group(1))

    assert list(CitationFailure.model_fields["reason"].annotation.__args__) == contract


def test_verification_report_wraps_literal_failures() -> None:
    assert VerificationReport.model_fields["failures"].annotation == list[CitationFailure]


# --- round-trip JSON ------------------------------------------------------------


@pytest.mark.parametrize(
    "instance",
    [
        _draft(),
        _draft(citations={}, unsupported_marked=False),
        _failure(sentence="La señora Ñuñoa niega la tesis [2]."),
        VerificationReport(passed=False, failures=[_failure(), _failure(chunk_id=CHUNK_B, reason="not_entailed")]),
        VerificationReport(passed=True, failures=[]),
        _piece(),
        PieceLog(consultation_id="20261107T120000Z-c3a1", pieces=[_piece(), _piece(index=1, text="¿Qué sigue? Año ñ.")]),
    ],
    ids=["DraftSection", "DraftSection-sin-citas", "CitationFailure", "Report-fallido", "Report-ok", "PieceRecord", "PieceLog"],
)
def test_json_round_trip(instance: BaseModel) -> None:
    dumped = instance.model_dump_json()

    assert type(instance).model_validate_json(dumped) == instance
    assert "\\u" not in dumped  # acentos, ñ y ⟨⟩ viajan como UTF-8, no escapados


def test_citations_keys_come_back_as_int() -> None:
    """JSON solo admite claves de texto: el `[n]` tiene que volver como entero, no como "1"."""
    dumped = _draft().model_dump_json()
    assert set(json.loads(dumped)["citations"]) == {"1", "2"}

    restored = DraftSection.model_validate_json(dumped)

    assert set(restored.citations) == {1, 2}
    assert restored.citations[2] == [CHUNK_B, CHUNK_A]  # el orden de los chunks se conserva


def test_unsupported_marker_survives_round_trip() -> None:
    draft = _draft(text="El ethos barroco nació en 1492 ⟨sin fuente⟩.", citations={})

    assert DraftSection.model_validate_json(draft.model_dump_json()).text.endswith("⟨sin fuente⟩.")


# --- C7: literales y coherencia de passed -----------------------------------------


@pytest.mark.parametrize("reason", ["not_entailed", "scope_mismatch", "chunk_not_found"])
def test_failure_accepts_the_three_reasons(reason: str) -> None:
    assert _failure(reason=reason).reason == reason


@pytest.mark.parametrize("reason", ["ok", "Not_entailed", "alcance", "", None])
def test_failure_rejects_other_reasons(reason: object) -> None:
    with pytest.raises(ValidationError, match="reason"):
        _failure(reason=reason)


def test_passed_report_with_failures_is_rejected() -> None:
    with pytest.raises(ValidationError, match="passed=True con 1 fallo"):
        VerificationReport(passed=True, failures=[_failure()])


def test_failed_report_without_citation_failures_is_allowed() -> None:
    """Un pedido puede fallar solo por piezas ⟨sin fuente⟩, que no tienen chunk_id (Y8)."""
    assert VerificationReport(passed=False, failures=[]).passed is False


# --- registro por pieza (Y7) ------------------------------------------------------


def test_piece_with_ok_verdict_is_verified() -> None:
    assert _piece().status == "verified"


def test_piece_with_one_bad_chunk_is_failed() -> None:
    piece = _piece(
        chunk_ids=[CHUNK_A, CHUNK_B],
        verdicts=[
            ChunkVerdict(chunk_id=CHUNK_A, verdict="ok", reason="lo dice"),
            ChunkVerdict(chunk_id=CHUNK_B, verdict="scope_mismatch", reason="el pasaje habla solo de México"),
        ],
        status="failed",
    )
    assert piece.status == "failed"


def test_cited_piece_without_verdict_is_an_error() -> None:
    """Y7: una pieza sin veredicto es un error, no un acierto."""
    with pytest.raises(ValidationError, match="sin veredicto"):
        _piece(verdicts=[])


def test_cited_piece_with_partial_verdicts_is_an_error() -> None:
    with pytest.raises(ValidationError, match="sin veredicto para"):
        _piece(chunk_ids=[CHUNK_A, CHUNK_B])


@pytest.mark.parametrize(
    ("verdict", "status"),
    [("ok", "failed"), ("not_entailed", "verified")],
)
def test_status_must_match_verdicts(verdict: str, status: str) -> None:
    with pytest.raises(ValidationError, match="no concuerda"):
        _piece(verdicts=[ChunkVerdict(chunk_id=CHUNK_A, verdict=verdict, reason="x")], status=status)


def test_verdict_for_uncited_chunk_is_rejected() -> None:
    with pytest.raises(ValidationError, match="no cita"):
        _piece(verdicts=[ChunkVerdict(chunk_id=CHUNK_B, verdict="ok", reason="x")])


def test_duplicated_verdict_is_rejected() -> None:
    v = ChunkVerdict(chunk_id=CHUNK_A, verdict="ok", reason="x")
    with pytest.raises(ValidationError, match="más de un veredicto"):
        _piece(verdicts=[v, v])


def test_duplicated_chunk_id_is_rejected() -> None:
    with pytest.raises(ValidationError, match="chunk_id repetido"):
        _piece(chunk_ids=[CHUNK_A, CHUNK_A])


def test_verdict_literal_rejects_unknown_values() -> None:
    with pytest.raises(ValidationError, match="verdict"):
        ChunkVerdict(chunk_id=CHUNK_A, verdict="probable", reason="x")


def test_uncited_factual_piece_is_unsupported() -> None:
    """Y8: pieza factual sin cita → ⟨sin fuente⟩."""
    piece = _piece(text="El barroco nació en 1492 ⟨sin fuente⟩.", chunk_ids=[], verdicts=[], status="unsupported")
    assert piece.status == "unsupported"


def test_uncited_factual_piece_cannot_pass_as_verified() -> None:
    with pytest.raises(ValidationError, match="sin chunk_ids"):
        _piece(chunk_ids=[], verdicts=[], status="verified")


def test_unsupported_piece_cannot_carry_chunks() -> None:
    with pytest.raises(ValidationError, match="no lleva chunk_ids"):
        _piece(verdicts=[], status="unsupported")


@pytest.mark.parametrize("kind", ["transition", "meta"])
def test_exempt_kinds_are_exempt(kind: str) -> None:
    piece = _piece(kind=kind, text="A continuación se examinan dos lecturas.", chunk_ids=[], verdicts=[], status="exempt")
    assert piece.status == "exempt"


def test_factual_piece_cannot_be_exempt() -> None:
    """Cierra la trampa del denominador (Y8): solo transición o meta-texto son exentas."""
    with pytest.raises(ValidationError, match="incompatible"):
        _piece(chunk_ids=[], verdicts=[], status="exempt")


def test_exempt_piece_cannot_carry_verdicts() -> None:
    with pytest.raises(ValidationError, match="no lleva veredictos"):
        _piece(kind="transition", status="exempt")


def test_unverified_piece_admits_missing_verdicts() -> None:
    """Corte por presupuesto (Y11): la pieza queda ⟨sin verificar⟩ sin veredicto."""
    assert _piece(verdicts=[], status="unverified", cycle=3).status == "unverified"


@pytest.mark.parametrize("pair_role", ["attribution", "objection", None])
def test_pair_role_literals(pair_role: str | None) -> None:
    assert _piece(pair_role=pair_role).pair_role == pair_role


def test_pair_role_rejects_other_values() -> None:
    with pytest.raises(ValidationError, match="pair_role"):
        _piece(pair_role="contradicts")


def test_piece_log_rejects_repeated_index_in_same_cycle() -> None:
    with pytest.raises(ValidationError, match="repetido"):
        PieceLog(consultation_id="x", pieces=[_piece(), _piece()])


def test_piece_log_allows_same_index_in_later_cycle() -> None:
    log = PieceLog(consultation_id="x", pieces=[_piece(), _piece(cycle=2)])
    assert [(p.index, p.cycle) for p in log.pieces] == [(0, 1), (0, 2)]
