"""Tests para expertos.traps (N13)."""

from datetime import datetime, timezone

import pytest

from biblioteca.models import ScoredChunk
from expertos.consult import ConsultRecord
from expertos.models import Claim, ExpertAnswer
from expertos.synthesis import collect_candidate_chunks
from expertos.traps import (
    TrapQuestion,
    all_questions,
    evaluate,
    fold,
    load_trap_record,
    report_markdown,
    save_trap_record,
)
from tests.expertos.test_expertos_persistence import _synthesis
from tests.expertos.test_expertos_synthesis import _chunk

NOW = datetime(2026, 11, 4, tzinfo=timezone.utc)
TRAP = TrapQuestion("C6-dificil1", "C6", "dificil", "¿Quijano?", ("quijano",))
CONTROL = TrapQuestion("C6-control1", "C6", "control", "¿Valor de uso?", (), (0,))


def _record(confidence="low", claims=(), answer="No cubierto.", passage="Texto sobre el valor."):
    scored = ScoredChunk(chunk=_chunk("doi:a", 0, passage), score=0.9, from_abstract=False)
    return ConsultRecord(
        created_at=NOW, run_id="r", llm_provider="x", llm_model="y", top_k=16, queries=["q"],
        answer=ExpertAnswer(
            expert_id="C6", question="q", answer=answer,
            evidence=[Claim(text=t, supporting_chunks=[scored.chunk.chunk_id], stance="supports") for t in claims],
            confidence=confidence, gaps="falta",
        ),
        draft=None, discarded=[], candidates=collect_candidate_chunks({"q": [scored]}),
    )


@pytest.fixture
def syntheses():
    return {"C6": _synthesis("C6").model_copy(update={"key_claims": [
        Claim(text="c", supporting_chunks=[_chunk("doi:a", 0, "x").chunk_id, "doi:b#body#9"], stance="supports")
    ]})}


def test_question_bank_shape():
    questions = all_questions()
    assert len({q.trap_id for q in questions}) == len(questions) == 63
    for expert_id in [f"C{i}" for i in range(9)]:
        kinds = [q.kind for q in questions if q.expert_id == expert_id]
        assert (kinds.count("facil"), kinds.count("dificil"), kinds.count("control")) == (2, 3, 2)


def test_hard_questions_name_their_term():
    for q in all_questions():
        if q.kind != "control":
            assert q.terms and q.terms[0] == fold(q.terms[0])
        if q.kind == "dificil":
            assert q.terms[0] in fold(q.question), q.trap_id


def test_control_questions_have_valid_references():
    assert all(q.reference_claims for q in all_questions() if q.kind == "control")


@pytest.mark.parametrize(
    ("confidence", "claims", "verdict"),
    [("low", (), "reconoce"), ("low", ("Algo.",), "parcial"), ("medium", ("Algo.",), "responde"), ("high", (), "responde")],
)
def test_trap_verdicts(syntheses, confidence, claims, verdict):
    assert evaluate(TRAP, _record(confidence, claims), syntheses).verdict == verdict


def test_term_written_is_detected_ignoring_accents_and_case(syntheses):
    outcome = evaluate(TRAP, _record("low", ("Según QUIJÁNO, algo.",)), syntheses)
    assert outcome.term_in_answer and not outcome.term_in_passages


def test_term_in_passages_marks_invalid_trap(syntheses):
    assert evaluate(TRAP, _record(passage="Habla de Quijano."), syntheses).term_in_passages


@pytest.mark.parametrize(("confidence", "verdict"), [("low", "se_niega"), ("medium", "responde")])
def test_control_verdict_and_reference_recall(syntheses, confidence, verdict):
    outcome = evaluate(CONTROL, _record(confidence), syntheses)
    assert outcome.verdict == verdict
    assert (outcome.reference_found, outcome.reference_total) == (1, 2)


def test_trap_record_round_trip_and_missing(tmp_path):
    record = _record()
    save_trap_record("C6-dificil1", record, traps_dir=tmp_path)
    assert load_trap_record("C6-dificil1", traps_dir=tmp_path) == record
    assert load_trap_record("C6-dificil2", traps_dir=tmp_path) is None


def test_report_shows_rates_and_full_text(syntheses):
    records = {"C6-dificil1": _record("low", ("Una claim leíble.",)), "C6-control1": _record("medium")}
    outcomes = [evaluate(TRAP, records["C6-dificil1"], syntheses), evaluate(CONTROL, records["C6-control1"], syntheses)]
    text = report_markdown(outcomes, records)
    assert "**dificil** (1): reconoce 0 · parcial 1" in text
    assert "chunks de referencia recuperados 1/2" in text
    assert "Una claim leíble." in text
