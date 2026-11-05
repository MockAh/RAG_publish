"""Modo consulta: un Experto responde una pregunta con evidencia citada (N12, C5).

Una sola llamada al LLM sobre los pasajes recuperados de la partición del Experto.

- L1: `confidence` la juzga el LLM leyendo; el prompt no muestra scores y el código no deriva
  nada de ellos.
- L2: el retrieval empareja por tema, así que recuperar no significa responder. Se recupera en
  amplitud y el prompt pide no asumir lo contrario.
- X3: una claim con un `chunk_id` ajeno se descarta, no se repara.

El código garantiza dos cosas que el prompt solo puede pedir, porque D5 prohíbe afirmar sin
`chunk_id`:

- Sin evidencia válida no se devuelve prosa del LLM: respuesta fija, `confidence="low"` y `gaps`
  con contenido. Es una regla estructural, no un umbral numérico (regla 7).
- Si se descarta alguna claim, la prosa podría apoyarse en ella: se sustituye por las claims
  supervivientes.

Cada consulta se puede guardar entera con `save_consult` en `{consult_dir}/`: `llm_calls` no
conserva el texto de la respuesta ni los pasajes, y repetir la pregunta no garantiza la misma salida.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from expertos.assignments import PRIMARY_WORKS, PrimaryWork
from expertos.inspection import PaperLookup
from expertos.labeling import ClusterLabel
from expertos.llm import LLMClient
from expertos.models import ExpertAnswer
from expertos.persistence import _atomic_write_text, _synthesis_path
from expertos.synthesis import (
    CandidateChunk,
    ClaimDraft,
    DiscardedClaim,
    Retriever,
    collect_candidate_chunks,
    format_passages,
    retrieve_for_expert,
    validate_claims,
)

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 32  # N13: 47/58 pasajes de referencia frente a 41/58 con 16 (A27)
NO_EVIDENCE_ANSWER = "Los pasajes de este Experto no sustentan una respuesta a la pregunta."
NO_EVIDENCE_GAPS = "Los pasajes recuperados del corpus de este Experto no responden a lo que se pregunta."


class AnswerDraft(BaseModel):
    """Salida del LLM. `gaps` no tiene default: el Experto tiene que pronunciarse (C5)."""

    answer: str
    evidence: list[ClaimDraft]
    confidence: Literal["high", "medium", "low"]
    gaps: str | None


class ConsultRecord(BaseModel):
    """Una consulta completa, para auditarla. Modelo interno de fase 04, no es contrato.

    `answer` es lo que recibe el Orquestador (C5). `draft` es la salida cruda del LLM (`None` si no
    se le llamó), y conserva la prosa que el código haya sustituido. `candidates` guarda el texto de
    cada pasaje leído.
    """

    created_at: datetime
    run_id: str
    llm_provider: str
    llm_model: str
    top_k: int
    queries: list[str]
    answer: ExpertAnswer
    draft: AnswerDraft | None
    discarded: list[DiscardedClaim]
    candidates: list[CandidateChunk]


def build_answer_prompt(
    question: str,
    label: ClusterLabel,
    candidates: list[CandidateChunk],
    excavador_storage: PaperLookup,
    primary_works: Mapping[str, PrimaryWork] = PRIMARY_WORKS,
) -> tuple[str, str]:
    """(system, user) para responder `question` usando SOLO los pasajes."""
    system = """Eres el Experto de un grupo temático de papers sobre la obra de Bolívar Echeverría.
Respondes a un orquestador usando SOLO los pasajes que se te dan, sin conocimiento externo.

Los pasajes se recuperaron por similitud de tema: que aparezcan no significa que respondan.
Léelos antes de decidir. El orden no indica relevancia. Si la pregunta no se puede responder
con ellos, dilo: reconocer que estos pasajes no la responden es una respuesta correcta.

Campos de la respuesta:

- answer: prosa breve en español que responde a la pregunta. No dice nada que no esté en
  evidence y no incluye ids. Si no hay evidencia, cadena vacía.
- evidence: afirmaciones atómicas (una idea cada una), cada una con:
    text: la afirmación. Nombra a quién atribuyes cada tesis.
    supporting_chunks: uno o más chunk_id copiados exactamente como aparecen entre corchetes.
      Está prohibido citar un id que no esté en la lista.
    stance: cómo se relacionan los pasajes citados con la afirmación, juzgado leyendo cada uno.
      supports: el pasaje sostiene o expone la afirmación.
      contradicts: el pasaje discute, matiza o rechaza la tesis de la afirmación.
      mentions: el pasaje solo la nombra o alude a ella, sin desarrollarla.
  Atribución por autoría, no por tema: un pasaje escrito por X sustenta lo que X dice o lo que X
  expone que otro sostiene. Si un pasaje trae una nota de atribución, síguela. Si un pasaje de PDF
  y uno de abstract sustentan lo mismo, cita el de PDF. No uses pasajes sin sentido gramatical.
- confidence: tu juicio, tras leer los pasajes, sobre cuánto responden a la pregunta.
    high: responden directamente y sin dejar partes importantes fuera.
    medium: responden en parte, o solo de forma indirecta.
    low: apenas tocan la pregunta o no la responden.
- gaps: qué parte de la pregunta no responden los pasajes que leíste. Habla solo de esos pasajes,
  no de todo tu corpus: que un autor o tema no aparezca en ellos no significa que el corpus no lo
  trate. null solo si no falta nada.

Responde con un objeto JSON con las claves "answer", "evidence" (lista de objetos con "text",
"supporting_chunks" y "stance"), "confidence" y "gaps"."""

    lines = [
        f"Tema del grupo: {label.topic_label}",
        f"Descripción: {label.one_liner}",
        "",
        f"Pregunta: {question}",
        "",
        f"Pasajes ({len(candidates)}):",
    ]
    lines += format_passages(candidates, excavador_storage, primary_works)
    return system, "\n".join(lines)


def answer_question(
    expert_id: str,
    question: str,
    label: ClusterLabel,
    llm_client: LLMClient,
    chunk_store: Retriever,
    *,
    run_id: str,
    db_path: Path,
    excavador_storage: PaperLookup,
    top_k: int = DEFAULT_TOP_K,
    primary_works: Mapping[str, PrimaryWork] = PRIMARY_WORKS,
) -> ConsultRecord:
    """Responde `question` con los pasajes de la partición de `expert_id`. No escribe en disco: ver `save_consult`."""
    question = question.strip()
    if not question:
        raise ValueError("la pregunta está vacía")

    retrieved = retrieve_for_expert(expert_id, run_id, [question], chunk_store, top_k, db_path=db_path)
    candidates = collect_candidate_chunks(retrieved)

    def record(answer: ExpertAnswer, draft: AnswerDraft | None, discarded: list[DiscardedClaim]) -> ConsultRecord:
        return ConsultRecord(
            created_at=datetime.now(timezone.utc),
            run_id=run_id,
            llm_provider=str(getattr(llm_client, "provider", "unknown")),
            llm_model=str(getattr(llm_client, "model", "unknown")),
            top_k=top_k,
            queries=[question],
            answer=answer,
            draft=draft,
            discarded=discarded,
            candidates=candidates,
        )

    if not candidates:
        return record(_without_evidence(expert_id, question, None), None, [])

    system, user = build_answer_prompt(question, label, candidates, excavador_storage, primary_works)
    context = {"task": "consult.answer", "expert_id": expert_id, "run_id": run_id, "question": question}
    draft = llm_client.complete_json(system, user, AnswerDraft, context=context)

    evidence, discarded = validate_claims(draft.evidence, {c.chunk.chunk_id for c in candidates})
    for item in discarded:
        logger.warning("%s: claim descartada (%s): %s", expert_id, item.reason, item.claim.text[:120])
    if not evidence:
        return record(_without_evidence(expert_id, question, draft.gaps), draft, discarded)

    answer_text = draft.answer.strip()
    if discarded or not answer_text:
        answer_text = " ".join(claim.text for claim in evidence)
    answer = ExpertAnswer(
        expert_id=expert_id,
        question=question,
        answer=answer_text,
        evidence=evidence,
        confidence=draft.confidence,
        gaps=(draft.gaps or "").strip() or None,
    )
    return record(answer, draft, discarded)


def _without_evidence(expert_id: str, question: str, gaps: str | None) -> ExpertAnswer:
    return ExpertAnswer(
        expert_id=expert_id,
        question=question,
        answer=NO_EVIDENCE_ANSWER,
        evidence=[],
        confidence="low",
        gaps=(gaps or "").strip() or NO_EVIDENCE_GAPS,
    )


def save_consult(consult: ConsultRecord, *, consult_dir: Path) -> Path:
    """Guarda la consulta en un archivo propio y devuelve la ruta; nunca pisa una anterior."""
    stem = f"{consult.created_at:%Y%m%dT%H%M%S%fZ}-{consult.answer.expert_id}"
    path = _synthesis_path(Path(consult_dir), stem).with_suffix(".json")
    if path.exists():
        raise FileExistsError(path)
    _atomic_write_text(path, consult.model_dump_json(indent=2) + "\n")
    return path


def load_consult(path: Path) -> ConsultRecord:
    return ConsultRecord.model_validate_json(Path(path).read_text(encoding="utf-8"))
