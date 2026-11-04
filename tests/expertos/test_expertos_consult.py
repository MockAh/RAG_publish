"""Tests para expertos.consult (N12: modo consulta, C5), con store y LLM dummy."""

import json

import pytest
from pydantic import ValidationError

from biblioteca.models import ScoredChunk
from expertos.assignments import PrimaryWork, save_assignment
from expertos.consult import (
    NO_EVIDENCE_ANSWER,
    NO_EVIDENCE_GAPS,
    AnswerDraft,
    answer_question,
    build_answer_prompt,
    load_consult,
    save_consult,
)
from expertos.llm import LLMOutputError
from expertos.synthesis import collect_candidate_chunks
from tests.expertos.test_expertos_labeling import _paper
from tests.expertos.test_expertos_synthesis import _chunk
from tests.expertos.test_expertos_synthesis_draft import _LABEL

RUN_ID = "kmeans-k9-seed42-0123abcd"
QUESTION = "¿Qué es el valor de uso?"
MARX = "doi:marx"
PRIMARY = {MARX: PrimaryWork(real_author="Karl Marx", attribution_note="Texto de Marx traducido por Echeverría.")}


class Storage:
    def get_paper(self, paper_id):
        return _paper(paper_id).model_copy(update={"authors": ["Metadato Engañoso"], "year": 2019})


class Store:
    def __init__(self, score=0.88, stray=False, empty=False):
        self.score, self.stray, self.empty = score, stray, empty
        self.calls = []

    def retrieve(self, query, top_k=8, filter_paper_ids=None):
        self.calls.append((query, top_k, filter_paper_ids))
        if self.empty:
            return []
        paper_ids = ["doi:ajeno"] if self.stray else filter_paper_ids
        return [
            ScoredChunk(chunk=_chunk(p, 0, f"Texto de {p}."), score=self.score, from_abstract=False)
            for p in paper_ids
        ]


class LLM:
    def __init__(self, output):
        self.output = output
        self.calls = []

    def complete_json(self, system, user, schema, *, context=None):
        self.calls.append({"system": system, "user": user, "schema": schema, "context": context})
        if isinstance(self.output, Exception):
            raise self.output
        return schema.model_validate_json(json.dumps(self.output))


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "t.db"
    save_assignment(path, RUN_ID, {"doi:a": "C6", MARX: "C6", "doi:otro": "C1"})
    return path


def _id(paper_id):
    return _chunk(paper_id, 0, "x").chunk_id


def _output(**update):
    return {
        "answer": "El valor de uso es central.",
        "evidence": [{"text": "Pérez lo expone.", "supporting_chunks": [_id("doi:a")], "stance": "supports"}],
        "confidence": "medium",
        "gaps": None,
    } | update


def _ask(db_path, output=None, store=None, **kwargs):
    llm, store = LLM(output or _output()), store or Store()
    result = answer_question(
        "C6", kwargs.pop("question", QUESTION), _LABEL, llm, store,
        run_id=RUN_ID, db_path=db_path, excavador_storage=Storage(), primary_works=PRIMARY, **kwargs,
    )
    return result, llm, store


def test_valid_answer_passes_through(db_path):
    result, llm, _ = _ask(db_path, _output(gaps="No cubre su recepción."))
    answer = result.answer
    assert (answer.expert_id, answer.question) == ("C6", QUESTION)
    assert answer.answer == "El valor de uso es central."
    assert [c.supporting_chunks for c in answer.evidence] == [[_id("doi:a")]]
    assert (answer.confidence, answer.gaps) == ("medium", "No cubre su recepción.")
    assert result.discarded == []
    assert llm.calls[0]["context"] == {
        "task": "consult.answer", "expert_id": "C6", "run_id": RUN_ID, "question": QUESTION,
    }


def test_retrieval_uses_the_question_inside_the_partition(db_path):
    _, _, store = _ask(db_path, top_k=5)
    query, top_k, paper_ids = store.calls[0]
    assert (query, top_k) == (QUESTION, 5)
    assert sorted(paper_ids) == ["doi:a", MARX]  # «doi:otro» es de C1


def test_chunk_outside_the_partition_is_an_error(db_path):
    with pytest.raises(RuntimeError, match="fuera de la partición"):
        _ask(db_path, store=Store(stray=True))


def test_expert_without_papers_is_an_error_and_does_not_search_everything(db_path):
    llm, store = LLM(_output()), Store()
    with pytest.raises(ValueError, match="no tiene papers"):
        answer_question(
            "C99", QUESTION, _LABEL, llm, store,
            run_id=RUN_ID, db_path=db_path, excavador_storage=Storage(),
        )
    assert store.calls == [] and llm.calls == []


@pytest.mark.parametrize("question", ["", "   "])
def test_empty_question_is_an_error(db_path, question):
    with pytest.raises(ValueError, match="vacía"):
        _ask(db_path, question=question)


@pytest.mark.parametrize(
    ("score", "judged"), [(0.60, "high"), (0.95, "low"), (0.88, "medium")]
)
def test_confidence_is_the_llm_judgement_regardless_of_score(db_path, score, judged):
    result, _, _ = _ask(db_path, _output(confidence=judged), store=Store(score=score))
    assert result.answer.confidence == judged


def test_prompt_never_shows_scores(db_path):
    _, llm, _ = _ask(db_path, store=Store(score=0.8765))
    assert "0.8765" not in llm.calls[0]["user"] and "0.8765" not in llm.calls[0]["system"]


def test_prompt_attributes_primary_work_to_real_author(db_path):
    _, llm, _ = _ask(db_path)
    user = llm.calls[0]["user"]
    assert "autor: Karl Marx" in user and "Texto de Marx traducido" in user
    assert f"Pregunta: {QUESTION}" in user


def test_foreign_chunk_discards_claim_and_rebuilds_prose(db_path):
    output = _output(
        answer="Prosa que se apoya también en la claim inventada.",
        evidence=[
            {"text": "Claim buena.", "supporting_chunks": [_id("doi:a")], "stance": "supports"},
            {"text": "Claim inventada.", "supporting_chunks": ["doi:zzz#body#0"], "stance": "supports"},
        ],
    )
    result, _, _ = _ask(db_path, output)
    assert result.answer.answer == "Claim buena."
    assert [c.text for c in result.answer.evidence] == ["Claim buena."]
    assert "chunk_id fuera de los recuperados" in result.discarded[0].reason


@pytest.mark.parametrize(
    "evidence",
    [[], [{"text": "Inventada.", "supporting_chunks": ["doi:zzz#body#0"], "stance": "supports"}]],
)
def test_no_valid_evidence_never_returns_llm_prose_or_high_confidence(db_path, evidence):
    output = _output(answer="Prosa sin citar.", evidence=evidence, confidence="high", gaps=None)
    answer = _ask(db_path, output)[0].answer
    assert answer.answer == NO_EVIDENCE_ANSWER
    assert (answer.evidence, answer.confidence, answer.gaps) == ([], "low", NO_EVIDENCE_GAPS)


def test_no_evidence_keeps_the_gaps_the_llm_declared(db_path):
    output = _output(answer="", evidence=[], confidence="low", gaps="Mi corpus no cubre a Hegel.")
    assert _ask(db_path, output)[0].answer.gaps == "Mi corpus no cubre a Hegel."


def test_no_passages_answers_without_calling_llm(db_path):
    result, llm, _ = _ask(db_path, store=Store(empty=True))
    assert llm.calls == []
    assert (result.answer.answer, result.answer.confidence) == (NO_EVIDENCE_ANSWER, "low")


def test_empty_prose_with_valid_evidence_uses_the_claims(db_path):
    assert _ask(db_path, _output(answer="  "))[0].answer.answer == "Pérez lo expone."


@pytest.mark.parametrize("gaps", ["", "   "])
def test_blank_gaps_become_none(db_path, gaps):
    assert _ask(db_path, _output(gaps=gaps))[0].answer.gaps is None


def test_gaps_is_required_in_llm_output():
    output = _output()
    del output["gaps"]
    with pytest.raises(ValidationError):
        AnswerDraft.model_validate(output)


def test_llm_error_propagates(db_path):
    with pytest.raises(LLMOutputError):
        _ask(db_path, LLMOutputError("JSON inválido"))


def test_build_prompt_warns_that_retrieval_is_not_an_answer():
    scored = ScoredChunk(chunk=_chunk("doi:a", 0, "Texto."), score=0.9, from_abstract=True)
    system, user = build_answer_prompt(QUESTION, _LABEL, collect_candidate_chunks({"q": [scored]}), Storage(), PRIMARY)
    assert "que aparezcan no significa que respondan" in system
    assert "fuente: abstract" in user


def test_record_keeps_what_the_answer_replaced(db_path):
    output = _output(
        answer="Prosa original del LLM.",
        evidence=[
            {"text": "Claim buena.", "supporting_chunks": [_id("doi:a")], "stance": "supports"},
            {"text": "Inventada.", "supporting_chunks": ["doi:zzz#body#0"], "stance": "supports"},
        ],
    )
    record = _ask(db_path, output, top_k=5)[0]
    assert record.answer.answer == "Claim buena."
    assert record.draft.answer == "Prosa original del LLM."
    assert (record.run_id, record.top_k, record.queries) == (RUN_ID, 5, [QUESTION])
    assert {c.chunk.text for c in record.candidates} == {"Texto de doi:a.", f"Texto de {MARX}."}


def test_no_passages_record_has_no_draft(db_path):
    assert _ask(db_path, store=Store(empty=True))[0].draft is None


def test_save_consult_round_trips_with_passage_text(db_path, tmp_path):
    record = _ask(db_path)[0]
    path = save_consult(record, consult_dir=tmp_path / "consult")
    assert path.parent == tmp_path / "consult" and path.suffix == ".json" and "C6" in path.name
    assert load_consult(path) == record
    assert "Texto de doi:a." in path.read_text(encoding="utf-8")


def test_save_consult_never_overwrites(db_path, tmp_path):
    record = _ask(db_path)[0]
    save_consult(record, consult_dir=tmp_path)
    with pytest.raises(FileExistsError):
        save_consult(record, consult_dir=tmp_path)


def test_two_consults_get_two_files(db_path, tmp_path):
    first, second = _ask(db_path)[0], _ask(db_path)[0]
    second = second.model_copy(update={"created_at": first.created_at.replace(microsecond=(first.created_at.microsecond + 1) % 1000000)})
    assert save_consult(first, consult_dir=tmp_path) != save_consult(second, consult_dir=tmp_path)
