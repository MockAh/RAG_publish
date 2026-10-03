"""Tests para expertos.synthesis, segunda fase (N8): claims validadas contra los candidatos de N7."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from biblioteca.models import ScoredChunk
from expertos.assignments import PrimaryWork
from expertos.labeling import ClusterLabel
from expertos.llm import LLMOutputError
from expertos.models import Claim
from expertos.persistence import load_synthesis
from expertos.synthesis import (
    CandidateChunk,
    NoValidClaimsError,
    RetrievalRecord,
    build_draft_prompt,
    draft_claims,
    load_draft_audit,
    run_expert_draft,
    save_retrieval,
)
from tests.expertos.test_expertos_labeling import _paper
from tests.expertos.test_expertos_synthesis import _chunk

RUN_ID = "kmeans-k9-seed42-0123abcd"
MARX = "doi:marx"

_LABEL = ClusterLabel(
    topic_label="Valor de uso y crítica de la economía política",
    one_liner="Papers sobre la lectura del valor de uso en Marx que propone Echeverría.",
    keywords=["valor de uso", "Marx", "forma natural", "reproducción social"],
    coherent=True,
    note=None,
)

_PRIMARY = {
    MARX: PrimaryWork(real_author="Karl Marx", attribution_note="Texto de Marx traducido por Echeverría.")
}

_SUMMARY = " ".join(["palabra"] * 350)


def _papers():
    return {
        "doi:a": _paper("doi:a").model_copy(update={"authors": ["Ana Pérez", "Luis Núñez"], "year": 2019}),
        "doi:b": _paper("doi:b").model_copy(update={"authors": ["Bea Ruiz"], "year": 2021}),
        MARX: _paper(MARX).model_copy(update={"authors": ["Metadato Engañoso"], "year": 2018}),
    }


class Storage:
    def __init__(self, papers) -> None:
        self._papers = papers

    def get_paper(self, paper_id):
        return self._papers.get(paper_id)


def _candidates() -> list[CandidateChunk]:
    return [
        CandidateChunk(chunk=_chunk("doi:a", 0, "El valor de uso es central."), score=0.88, from_abstract=False, queries=["q1"]),
        CandidateChunk(chunk=_chunk("doi:b", 0, "Se discute esa lectura."), score=0.84, from_abstract=True, queries=["q1"]),
        CandidateChunk(chunk=_chunk(MARX, 0, "La riqueza de las sociedades…"), score=0.81, from_abstract=False, queries=["q2"]),
    ]


A, B, M = (c.chunk.chunk_id for c in _candidates())


def _claim(text: str, chunks: list[str], stance: str = "supports") -> dict:
    return {"text": text, "supporting_chunks": chunks, "stance": stance}


class DummyLLM:
    """Imita al cliente real: valida contra el schema y envuelve el fallo en `LLMOutputError`."""

    provider = "dummy"
    model = "dummy-model"

    def __init__(self, claims: list[dict], summary: str = _SUMMARY) -> None:
        self.calls: list[tuple[str, str]] = []
        self.contexts: list[dict | None] = []
        self._raw = json.dumps({"summary": summary, "key_claims": claims}, ensure_ascii=False)

    def complete_json(self, system, user, schema, *, context=None):
        self.calls.append((system, user))
        self.contexts.append(context)
        try:
            return schema.model_validate_json(self._raw)
        except ValidationError as exc:
            raise LLMOutputError(str(exc)) from exc


def _draft(llm: DummyLLM):
    return draft_claims(
        "C1",
        _LABEL,
        _candidates(),
        llm,
        run_id=RUN_ID,
        paper_ids=["doi:a", "doi:b", MARX, "doi:sin-citar"],
        excavador_storage=Storage(_papers()),
        primary_works=_PRIMARY,
    )


# --- validación en código ---------------------------------------------------------


def test_draft_makes_exactly_one_call_with_context() -> None:
    llm = DummyLLM([_claim("Echeverría centra su lectura en el valor de uso.", [A])])

    _draft(llm)

    assert len(llm.calls) == 1
    assert llm.contexts == [{"task": "synthesis.draft", "expert_id": "C1", "run_id": RUN_ID}]


def test_claim_with_foreign_chunk_id_is_discarded_whole_and_others_survive() -> None:
    llm = DummyLLM(
        [
            _claim("Válida.", [A]),
            _claim("Mezcla un id real y uno inventado.", [A, "doi:z#body#9"]),
            _claim("También válida.", [B], "mentions"),
        ]
    )

    synthesis, audit = _draft(llm)

    assert [c.text for c in synthesis.key_claims] == ["Válida.", "También válida."]
    assert (audit.n_proposed, audit.n_kept, len(audit.discarded)) == (3, 2, 1)
    [discarded] = audit.discarded
    assert discarded.claim.supporting_chunks == [A, "doi:z#body#9"]  # sin reparar
    assert "doi:z#body#9" in discarded.reason


def test_empty_supporting_chunks_is_rejected_by_the_model_and_discarded() -> None:
    with pytest.raises(ValidationError):
        Claim(text="Sin soporte.", supporting_chunks=[], stance="supports")

    synthesis, audit = _draft(DummyLLM([_claim("Sin soporte.", []), _claim("Con soporte.", [A])]))

    assert [c.text for c in synthesis.key_claims] == ["Con soporte."]
    assert "supporting_chunks" in audit.discarded[0].reason


def test_unknown_stance_is_discarded_not_coerced() -> None:
    synthesis, audit = _draft(DummyLLM([_claim("Postura rara.", [A], "neutral"), _claim("Bien.", [A])]))

    assert [c.text for c in synthesis.key_claims] == ["Bien."]
    assert "stance" in audit.discarded[0].reason


def test_no_surviving_claim_raises_and_nothing_is_built() -> None:
    with pytest.raises(NoValidClaimsError, match="ninguna de las 1"):
        _draft(DummyLLM([_claim("Inventada.", ["doi:z#body#0"])]))


def test_summary_out_of_c3_range_invalidates_the_response() -> None:
    with pytest.raises(LLMOutputError, match="summary"):
        _draft(DummyLLM([_claim("Válida.", [A])], summary="Demasiado corto."))


def test_three_stances_are_accepted_and_persisted(tmp_path: Path) -> None:
    from expertos.persistence import save_synthesis

    llm = DummyLLM(
        [
            _claim("Echeverría sostiene X.", [A], "supports"),
            _claim("Echeverría sostiene X (discutido).", [B], "contradicts"),
            _claim("Se alude a X.", [A], "mentions"),
        ]
    )

    synthesis, _ = _draft(llm)
    save_synthesis(synthesis, synthesis_dir=tmp_path)

    loaded = load_synthesis("C1", synthesis_dir=tmp_path)
    assert [c.stance for c in loaded.key_claims] == ["supports", "contradicts", "mentions"]
    assert loaded == synthesis


def test_synthesis_covers_the_partition_not_only_cited_papers() -> None:
    synthesis, _ = _draft(DummyLLM([_claim("Válida.", [A])]))

    assert synthesis.paper_ids == ["doi:a", "doi:b", MARX, "doi:sin-citar"]
    assert synthesis.topic_label == _LABEL.topic_label
    assert synthesis.synthesis_id.startswith(f"{RUN_ID}/C1/")


# --- prompt ---------------------------------------------------------------------


def test_prompt_carries_author_year_source_and_id_of_every_chunk() -> None:
    llm = DummyLLM([_claim("Válida.", [A])])

    _draft(llm)

    system, user = llm.calls[0]
    assert f"[{A}]\npaper_id: doi:a · autor: Ana Pérez; Luis Núñez · año: 2019 · fuente: PDF" in user
    assert f"[{B}]\npaper_id: doi:b · autor: Bea Ruiz · año: 2021 · fuente: abstract" in user
    assert "Atribución por autoría" in system
    assert "No asumas supports por defecto" in system
    # A19: la crítica va en stance, con la tesis atribuida en el texto; nunca «X critica Y» con supports.
    assert "Tesis discutidas (obligatorio)" in system
    assert "El disenso va en stance, no en la frase" in system
    assert "cita el de PDF" in system


def test_primary_work_real_author_replaces_metadata_authors_with_its_note() -> None:
    llm = DummyLLM([_claim("Válida.", [A])])

    _draft(llm)

    _, user = llm.calls[0]
    header = f"[{M}]\npaper_id: {MARX} · autor: Karl Marx · año: 2018 · fuente: PDF\nnota de atribución: Texto de Marx traducido por Echeverría."
    assert header in user
    assert "Metadato Engañoso" not in user
    # Los demás papers no llevan nota.
    assert user.count("nota de atribución:") == 1


def test_prompt_does_not_show_scores() -> None:
    _, user = build_draft_prompt(_LABEL, _candidates(), Storage(_papers()), _PRIMARY)

    assert "0.88" not in user and "0.81" not in user


def test_claim_citing_primary_work_is_kept_and_flagged_for_audit() -> None:
    llm = DummyLLM(
        [
            _claim("Echeverría lee el valor de uso.", [A]),
            _claim("Marx abre El capital con la mercancía.", [M, A]),
        ]
    )

    synthesis, audit = _draft(llm)

    assert len(synthesis.key_claims) == 2  # no se descarta
    [flag] = audit.primary_work_flags
    assert (flag.claim_index, flag.paper_id, flag.chunk_ids, flag.real_author) == (1, MARX, [M], "Karl Marx")


# --- orquestación y archivos ---------------------------------------------------------


def test_run_expert_draft_reads_retrieval_and_writes_synthesis_and_audit_to_out_dir(tmp_path: Path) -> None:
    synthesis_dir, out_dir = tmp_path / "synthesis", tmp_path / "cmp" / "modelo"
    save_retrieval(
        RetrievalRecord(
            expert_id="C1",
            run_id=RUN_ID,
            created_at=datetime(2026, 10, 3, tzinfo=timezone.utc),
            llm_provider="dummy",
            llm_model="dummy",
            topic_label=_LABEL.topic_label,
            paper_ids=["doi:a", "doi:b", MARX],
            top_k=8,
            queries=["q1", "q2"],
            candidates=_candidates(),
        ),
        synthesis_dir=synthesis_dir,
    )
    llm = DummyLLM([_claim("Válida, con ñ y acentos: «barroco».", [A]), _claim("Ajena.", ["x#y#0"])])

    result = run_expert_draft(
        "C1", llm, run_id=RUN_ID, label=_LABEL, excavador_storage=Storage(_papers()),
        synthesis_dir=synthesis_dir, out_dir=out_dir,
    )

    assert load_synthesis("C1", synthesis_dir=out_dir) == result.synthesis
    assert load_draft_audit("C1", synthesis_dir=out_dir) == result.audit
    assert load_synthesis("C1", synthesis_dir=synthesis_dir) is None  # producción intacta
    assert result.audit.llm_model == "dummy-model" and len(result.audit.discarded) == 1


def test_run_expert_draft_without_retrieval_fails_before_calling_the_llm(tmp_path: Path) -> None:
    llm = DummyLLM([_claim("Válida.", [A])])

    with pytest.raises(FileNotFoundError, match="correr N7"):
        run_expert_draft("C1", llm, run_id=RUN_ID, label=_LABEL, excavador_storage=Storage(_papers()), synthesis_dir=tmp_path)
    assert llm.calls == []


# --- corrida real -----------------------------------------------------------------


@pytest.mark.slow
def test_real_draft_for_one_cluster() -> None:
    """Extremo a extremo desde la raíz del repo: C8, 1 llamada al LLM de síntesis.

    Lee el retrieval de producción (N7) y escribe en `data/synthesis_slowtest/` (fuera de git).
    """
    from excavador.storage import Storage as ExcavadorStorage
    from expertos.config import Settings
    from expertos.labeling import load_labels
    from expertos.llm import make_client
    from expertos.synthesis import load_retrieval

    try:
        settings = Settings()
    except ValidationError:
        pytest.skip("Configuración de Expertos incompleta")
    expert_id, run_id = "C8", settings.cluster_run_id
    record = load_retrieval(expert_id, synthesis_dir=settings.synthesis_dir)
    if record is None:
        pytest.skip("Falta el retrieval de N7 para C8")
    out_dir = settings.synthesis_dir.with_name("synthesis_slowtest")

    synthesis, audit = run_expert_draft(
        expert_id,
        make_client("synthesis", settings),
        run_id=run_id,
        label=load_labels(settings.cluster_labels_path, run_id)[expert_id],
        excavador_storage=ExcavadorStorage(settings.db_path),
        synthesis_dir=settings.synthesis_dir,
        out_dir=out_dir,
    )

    retrieved = {c.chunk.chunk_id for c in record.candidates}
    assert synthesis.key_claims
    assert all(set(c.supporting_chunks) <= retrieved for c in synthesis.key_claims)
    assert audit.n_kept + len(audit.discarded) == audit.n_proposed
    assert load_synthesis(expert_id, synthesis_dir=out_dir) == synthesis
