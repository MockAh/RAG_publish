"""Preguntas trampa y de control para el modo consulta (N13, criterio 4).

Tres tipos de pregunta por Experto:

- `facil` (2): nada que ver con el corpus.
- `dificil` (3): autor o concepto vecino, cercano al corpus, que NO aparece en ningún chunk de la
  partición de ese Experto. Muchas traen premisa falsa («¿cómo retoma Echeverría…?») a propósito:
  es donde un Experto puede responder de más.
- `control` (2): sí se pueden responder. Una concreta y una amplia, derivadas de claims de N9. Miden
  si el Experto se niega de más y si la búsqueda con la pregunta tal cual trae los chunks que esas
  claims citan: es el dato para decidir si hacen falta sub-consultas.

Una claim no se juzga fiel aquí: lo automático separa los casos, y la lectura final es manual.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Literal, NamedTuple

from expertos.consult import ConsultRecord
from expertos.models import Synthesis
from expertos.persistence import _atomic_write_text, _synthesis_path

Kind = Literal["facil", "dificil", "control"]


class TrapQuestion(NamedTuple):
    trap_id: str
    expert_id: str
    kind: Kind
    question: str
    terms: tuple[str, ...] = ()  # sin acentos y en minúsculas; ausentes de la partición
    reference_claims: tuple[int, ...] = ()  # índices en `Synthesis.key_claims` (control)


_EASY = (
    ("¿Qué técnica de fermentación se usa para el pan de masa madre?", "masa madre"),
    ("¿Cómo funciona la fotosíntesis en las plantas C4?", "fotosintesis"),
)
_GRAMSCI = ("¿Cómo retoma Echeverría el concepto de hegemonía de Gramsci?", "gramsci")
_QUIJANO = ("¿Cómo define Aníbal Quijano la colonialidad del poder?", "quijano")
_MARIATEGUI = ("¿Qué aporta Mariátegui al socialismo indoamericano en la lectura de Echeverría?", "mariategui")
_POLANYI = ("¿Cómo usa Echeverría la idea de la gran transformación de Karl Polanyi?", "polanyi")
_FOUCAULT = ("¿Qué relación plantea Echeverría entre la biopolítica de Foucault y la modernidad?", "foucault")
_BLANQUITUD = ("¿Qué es la blanquitud según Echeverría?", "blanquitud")
_ADORNO = ("¿Cómo se relaciona la industria cultural de Adorno con la obra de Echeverría?", "adorno")
_BRAUDEL = ("¿Qué entiende Braudel por larga duración y cómo la usa Echeverría?", "braudel")

_HARD: dict[str, tuple[tuple[str, str], ...]] = {
    "C0": (_QUIJANO, _GRAMSCI, _MARIATEGUI),
    "C1": (_GRAMSCI, _POLANYI, ("¿Qué lectura hace Echeverría del conatus de Spinoza?", "spinoza")),
    "C2": (_FOUCAULT, _POLANYI, ("¿Cómo se vincula el ethos con el habitus de Bourdieu?", "bourdieu")),
    "C3": (_QUIJANO, _ADORNO, ("¿Qué toma Echeverría de la crítica de la técnica de Heidegger?", "heidegger")),
    "C4": (_GRAMSCI, _FOUCAULT, ("¿Qué dice Echeverría sobre la banalidad del mal de Hannah Arendt?", "arendt")),
    "C5": (
        _BLANQUITUD,
        ("¿Cuáles son los rasgos del ethos barroco según Echeverría?", "barroco"),
        ("¿Cómo interpreta Echeverría el ángel de la historia de Walter Benjamin?", "benjamin"),
    ),
    "C6": (_QUIJANO, _BRAUDEL, _MARIATEGUI),
    "C7": (_BLANQUITUD, _ADORNO, _QUIJANO),
    "C8": (_BLANQUITUD, _ADORNO, _BRAUDEL),
}

# (pregunta, claims de referencia): primero la concreta, luego la amplia.
_CONTROL: dict[str, tuple[tuple[str, tuple[int, ...]], ...]] = {
    "C0": (
        ("¿Qué postura defiende Echeverría frente a los fundamentalismos religiosos?", (6,)),
        ("¿Qué críticas a la modernidad reúnen estos trabajos?", (1, 9, 10, 11)),
    ),
    "C1": (
        ("¿Qué entiende Echeverría por blanquitud?", (4,)),
        ("¿Cómo cambió la idea de revolución en el pensamiento de Echeverría?", (10, 11, 12)),
    ),
    "C2": (
        ("¿Cómo fundamenta Echeverría su teoría de la cultura?", (8,)),
        ("¿Cómo se articulan los cuatro ethe con la contradicción entre valor y valor de uso?", (2, 3, 4)),
    ),
    "C3": (
        ("¿Qué relación plantea Echeverría entre barroco y mestizaje?", (2,)),
        ("¿Qué límites se le señalan a la noción de ethos barroco?", (3, 8, 9)),
    ),
    "C4": (
        ("¿Dónde nace el ethos barroco según Echeverría?", (13,)),
        ("¿Qué se discute sobre el ethos barroco como modernidad alternativa?", (5, 6, 7)),
    ),
    "C5": (
        ("¿Qué modelos de oposición entre campo y ciudad propone Echeverría?", (4,)),
        ("¿Qué lugar ocupa Marx en la formación del pensamiento de Echeverría?", (6, 7, 9, 10)),
    ),
    "C6": (
        ("¿Qué significa transnaturalización?", (5,)),
        ("¿Cómo se enfrentan valor de uso y valor en la modernidad capitalista?", (8, 9, 10)),
    ),
    "C7": (
        ("¿Quiénes participaron en la mesa sobre Benjamin del homenaje?", (8,)),
        ("¿Qué temas se trataron en el homenaje a Echeverría?", (5, 6, 7, 8)),
    ),
    "C8": (
        ("¿Por qué Echeverría considera metafísico a Sartre?", (6,)),
        ("¿Qué crítica hace Echeverría al humanismo y al existencialismo?", (4, 6, 7)),
    ),
}


def all_questions() -> list[TrapQuestion]:
    questions: list[TrapQuestion] = []
    for expert_id in sorted(_HARD, key=lambda e: int(e[1:])):
        for i, (question, term) in enumerate(_EASY, start=1):
            questions.append(TrapQuestion(f"{expert_id}-facil{i}", expert_id, "facil", question, (term,)))
        for i, (question, term) in enumerate(_HARD[expert_id], start=1):
            questions.append(TrapQuestion(f"{expert_id}-dificil{i}", expert_id, "dificil", question, (term,)))
        for i, (question, claims) in enumerate(_CONTROL[expert_id], start=1):
            questions.append(TrapQuestion(f"{expert_id}-control{i}", expert_id, "control", question, (), claims))
    return questions


def fold(text: str) -> str:
    """Minúsculas y sin acentos, para buscar términos también en los abstracts degradados."""
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if not unicodedata.combining(c))


class Outcome(NamedTuple):
    trap: TrapQuestion
    confidence: str
    n_evidence: int
    verdict: str
    term_in_answer: bool  # el término aparece en la respuesta o en una claim (trampas)
    term_in_passages: bool  # el término aparece en lo leído: la trampa no sería válida
    reference_found: int  # chunks de referencia recuperados (control)
    reference_total: int


def _reference_chunks(trap: TrapQuestion, syntheses: Mapping[str, Synthesis]) -> set[str]:
    claims = syntheses[trap.expert_id].key_claims
    return {chunk_id for index in trap.reference_claims for chunk_id in claims[index].supporting_chunks}


def evaluate(trap: TrapQuestion, record: ConsultRecord, syntheses: Mapping[str, Synthesis]) -> Outcome:
    """Clasifica sin juzgar fidelidad. Trampa: `reconoce` | `parcial` | `responde`. Control: `responde` | `se_niega`."""
    answer = record.answer
    if trap.kind == "control":
        verdict = "se_niega" if answer.confidence == "low" else "responde"
    elif answer.confidence != "low":
        verdict = "responde"
    else:
        verdict = "parcial" if answer.evidence else "reconoce"

    written = fold(" ".join([answer.answer, *(claim.text for claim in answer.evidence)]))
    passages = fold(" ".join(candidate.chunk.text for candidate in record.candidates))
    reference = _reference_chunks(trap, syntheses)
    retrieved = {candidate.chunk.chunk_id for candidate in record.candidates}
    return Outcome(
        trap=trap,
        confidence=answer.confidence,
        n_evidence=len(answer.evidence),
        verdict=verdict,
        term_in_answer=any(term in written for term in trap.terms),
        term_in_passages=any(term in passages for term in trap.terms),
        reference_found=len(reference & retrieved),
        reference_total=len(reference),
    )


def trap_path(trap_id: str, *, traps_dir: Path) -> Path:
    return _synthesis_path(Path(traps_dir), trap_id).with_suffix(".json")


def save_trap_record(trap_id: str, record: ConsultRecord, *, traps_dir: Path) -> Path:
    path = trap_path(trap_id, traps_dir=traps_dir)
    _atomic_write_text(path, record.model_dump_json(indent=2) + "\n")
    return path


def load_trap_record(trap_id: str, *, traps_dir: Path) -> ConsultRecord | None:
    path = trap_path(trap_id, traps_dir=traps_dir)
    return ConsultRecord.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None


def report_markdown(outcomes: Iterable[Outcome], records: Mapping[str, ConsultRecord]) -> str:
    """Informe para revisión manual: tasas y, debajo, cada caso que exige leerse."""
    outcomes = list(outcomes)
    lines = ["# N13 · Preguntas trampa y control", ""]
    for kind in ("facil", "dificil"):
        group = [o for o in outcomes if o.trap.kind == kind]
        counts = {v: sum(o.verdict == v for o in group) for v in ("reconoce", "parcial", "responde")}
        lines.append(
            f"- **{kind}** ({len(group)}): reconoce {counts['reconoce']} · parcial {counts['parcial']} · "
            f"responde {counts['responde']} · con el término en lo escrito {sum(o.term_in_answer for o in group)}"
        )
    control = [o for o in outcomes if o.trap.kind == "control"]
    lines.append(
        f"- **control** ({len(control)}): responde {sum(o.verdict == 'responde' for o in control)} · "
        f"se niega {sum(o.verdict == 'se_niega' for o in control)} · chunks de referencia recuperados "
        f"{sum(o.reference_found for o in control)}/{sum(o.reference_total for o in control)}"
    )
    lines += ["", "| Pregunta | Veredicto | confidence | Claims | Término escrito | Término leído | Referencia |", "|---|---|---|---|---|---|---|"]
    for o in outcomes:
        reference = f"{o.reference_found}/{o.reference_total}" if o.trap.kind == "control" else "—"
        lines.append(
            f"| {o.trap.trap_id} | {o.verdict} | {o.confidence} | {o.n_evidence} | "
            f"{'sí' if o.term_in_answer else 'no'} | {'sí' if o.term_in_passages else 'no'} | {reference} |"
        )
    for o in outcomes:
        record = records[o.trap.trap_id]
        lines += ["", f"## {o.trap.trap_id} · {o.verdict}", "", f"**Pregunta:** {o.trap.question}", ""]
        lines += [f"**Respuesta:** {record.answer.answer}", "", f"**gaps:** {record.answer.gaps}", ""]
        lines += [f"- [{c.stance}] {c.text} `{', '.join(c.supporting_chunks)}`" for c in record.answer.evidence]
    return "\n".join(lines) + "\n"
