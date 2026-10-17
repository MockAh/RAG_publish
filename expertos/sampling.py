"""Muestreo manual de claims (N10): criterio de aceptación 3 de la spec 04, sin LLM.

Criterio 3: «10 claims al azar; ≥ 9 realmente sustentadas por su pasaje». Ajuste del plan
(E6 de fase 03): cada fallo se clasifica, porque ~10 % de los chunks de cuerpo están rotos
por la transcripción y eso no es culpa del Experto. Cuatro veredictos:

- `ok`: el pasaje sustenta la claim tal como está escrita.
- `claim_infiel`: el pasaje no dice eso, o la claim lo sobregeneraliza. Cuenta contra el Experto.
- `chunk_roto`: el pasaje está mal transcrito (E6) y no se puede juzgar. No cuenta: sale del
  denominador.
- `stance_erroneo`: el pasaje sustenta el texto de la claim, pero la postura está mal clasificada
  (A19). NO cuenta como sustentada: la claim C3 es texto + postura, y la postura es lo que
  leerá el Redactor.

Dos tasas, sobre los juzgables (`ok` + `claim_infiel` + `stance_erroneo`; `chunk_roto` fuera):

- criterio 3 = `ok` / juzgables;
- acierto de stance = `ok` / (`ok` + `stance_erroneo`): de las claims cuyo pasaje sí dice eso,
  cuántas tienen bien la postura.

**Estratificación (A23 del registro).** Tres estratos disjuntos:

- `contradicts`: los 7 de N9. Un muestreo uniforme de 10 sobre 128 los deja fuera con
  probabilidad ~(121/128)^10 ≈ 57 %, y son el caso raro y frágil (la vía `contradicts` se abrió
  con un cambio de prompt, A19). Entra un cupo fijo (`contradicts_quota`, 3), al azar. No 7:
  entonces el criterio 3 se mediría sobre 3 de las 121 `supports` (`--contradicts 7` los mete).
- `mencion`: claims `supports` con marcador léxico fuerte de mención de pasada
  (`mention_candidates`). N9 dio 0 `mentions` en 128 claims, lo que es poco verosímil; si hay
  `mentions` mal clasificadas como `supports`, viven aquí. Entran las elegidas a mano leyendo
  el anexo A (`mention_ids`) o, sin ellas, `mention_quota` al azar.
- `corriente`: todas las demás; completa la muestra, uniforme.

Como la muestra se inclina a propósito hacia los estratos raros, la tasa cruda no estima la del
corpus. Ambas tasas se dan también ponderadas por el tamaño de cada estrato en la población, y
**el criterio 3 se juzga por la ponderada**.

El texto de cada chunk sale de `_retrieval/{expert_id}.json` (N7), limpiado como en el prompt
de N8: es exactamente lo que leyó el modelo. Que esos chunks existen en la Biblioteca ya lo
comprobó N9 (criterio 2, `get_chunk`).

Dos informes más, tampoco con LLM: claims `supports` cuyo verbo sugiere mención de pasada
(N9: 0 `mentions` en 128 claims) y concentración de fuentes por clúster.
"""

from __future__ import annotations

import random
import re
import textwrap
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from expertos.assignments import PRIMARY_WORKS, PrimaryWork
from expertos.inspection import PaperLookup
from expertos.labeling import _clean
from expertos.models import Claim, Synthesis
from expertos.persistence import _atomic_write_text
from expertos.synthesis import RetrievalRecord

DEFAULT_CONTRADICTS_QUOTA = 3
DEFAULT_MENTION_QUOTA = 3
CRITERION_3_MIN_RATE = 0.9  # ≥ 9 de 10
STANCES = ("supports", "contradicts", "mentions")
STRATA = ("corriente", "mencion", "contradicts")

VerdictLabel = Literal["ok", "claim_infiel", "chunk_roto", "stance_erroneo"]
VERDICTS: tuple[str, ...] = VerdictLabel.__args__
VERDICT_HELP = {
    "ok": "el pasaje sustenta la claim tal como está escrita.",
    "claim_infiel": "el pasaje no dice eso, o la claim lo sobregeneraliza. Cuenta contra el Experto.",
    "chunk_roto": "el pasaje está mal transcrito (E6), así que no se puede juzgar. No cuenta contra el Experto.",
    "stance_erroneo": (
        "el pasaje sustenta el texto de la claim, pero la postura está mal clasificada (p. ej. discute "
        "la tesis y dice supports, o solo la nombra y dice supports). No cuenta como sustentada; "
        "además baja la tasa de acierto de stance (A19)."
    ),
}


def claim_id(expert_id: str, index: int) -> str:
    """`C3#4`: clúster y posición en `Synthesis.key_claims`."""
    return f"{expert_id}#{index}"


def _expert_order(expert_id: str) -> tuple[int, str]:
    digits = expert_id[1:]
    return (int(digits), expert_id) if digits.isdigit() else (10**9, expert_id)


def _strip_authors(text: str) -> str:
    """El texto sin el paréntesis final de autores que añade la regla de N8 («… (pasajes de X).»)."""
    return re.sub(r"\s*\([^()]*\)\s*\.?\s*$", "", text)


def _thesis_key(text: str) -> str:
    """Clave de tesis: los pares de A19 solo difieren en el paréntesis final de autores."""
    return " ".join(_strip_authors(text).lower().split())


class ReviewChunk(BaseModel):
    chunk_id: str
    paper_id: str
    title: str
    authors: list[str]
    year: int
    from_abstract: bool
    primary_work: PrimaryWork | None
    text: str  # limpiado como en el prompt de N8


class IndexedClaim(BaseModel):
    index: int
    claim: Claim


class SampledClaim(BaseModel):
    expert_id: str
    claim_index: int
    stratum: str  # uno de STRATA
    synthesis_id: str
    claim: Claim
    chunks: list[ReviewChunk]
    # Claims del mismo clúster con la misma tesis y otra postura (pares de A19): para juzgar el stance.
    twins: list[IndexedClaim]

    @property
    def claim_id(self) -> str:
        return claim_id(self.expert_id, self.claim_index)


def _chunk_index(retrievals: Mapping[str, RetrievalRecord]) -> dict[str, dict]:
    return {
        c.chunk.chunk_id: {"chunk": c.chunk, "from_abstract": c.from_abstract}
        for record in retrievals.values()
        for c in record.candidates
    }


def _claim_pool(syntheses: Mapping[str, Synthesis]) -> list[tuple[str, int, Claim]]:
    """Todas las claims, en orden estable (clúster numérico, posición)."""
    return [
        (eid, index, claim)
        for eid in sorted(syntheses, key=_expert_order)
        for index, claim in enumerate(syntheses[eid].key_claims)
    ]


def strata(syntheses: Mapping[str, Synthesis]) -> dict[tuple[str, int], str]:
    """Estrato de cada claim: `contradicts` por stance, `mencion` si es candidata fuerte, si no `corriente`."""
    strong = {m.claim_id for m in mention_candidates(syntheses) if m.strength == "fuerte"}
    return {
        (eid, i): "contradicts" if c.stance == "contradicts" else "mencion" if claim_id(eid, i) in strong else "corriente"
        for eid, i, c in _claim_pool(syntheses)
    }


def population_by_stratum(syntheses: Mapping[str, Synthesis]) -> dict[str, int]:
    counts = Counter(strata(syntheses).values())
    return {stratum: counts.get(stratum, 0) for stratum in STRATA}


def select_claims(
    syntheses: Mapping[str, Synthesis],
    n: int = 10,
    seed: int = 42,
    contradicts_quota: int = DEFAULT_CONTRADICTS_QUOTA,
    mention_quota: int = DEFAULT_MENTION_QUOTA,
    mention_ids: Sequence[str] | None = None,
) -> list[tuple[str, int, str]]:
    """(expert_id, índice, estrato) de la muestra estratificada, en orden de clúster y posición.

    `contradicts`: `min(contradicts_quota, disponibles)` al azar. `mencion`: las de `mention_ids`
    (cada una debe ser candidata fuerte) o, sin ellas, `mention_quota` al azar. `corriente`: el
    resto de la muestra, al azar. Si `corriente` no alcanza, se completa con los otros estratos.
    Misma semilla, mismas síntesis y mismos ids → misma muestra.
    """
    by_claim = strata(syntheses)
    if n > len(by_claim):
        raise ValueError(f"se piden {n} claims y solo hay {len(by_claim)}")
    pool = {stratum: [key for key, st in by_claim.items() if st == stratum] for stratum in STRATA}
    rng = random.Random(seed)
    chosen_contra = rng.sample(pool["contradicts"], min(contradicts_quota, len(pool["contradicts"]), n))
    if mention_ids:
        wanted = []
        for cid in mention_ids:
            eid, _, index = cid.partition("#")
            key = (eid, int(index)) if index.isdigit() else None
            if key not in pool["mencion"]:
                raise ValueError(f"{cid} no es candidata fuerte a mention (ver anexo A)")
            wanted.append(key)
        chosen_mention = list(dict.fromkeys(wanted))
    else:
        chosen_mention = rng.sample(pool["mencion"], min(mention_quota, len(pool["mencion"]), n - len(chosen_contra)))
    room = n - len(chosen_contra) - len(chosen_mention)
    if room < 0:
        raise ValueError(f"{len(chosen_contra)} contradicts + {len(chosen_mention)} mention_ids superan n = {n}")
    chosen_rest = rng.sample(pool["corriente"], min(room, len(pool["corriente"])))
    chosen = chosen_contra + chosen_mention + chosen_rest
    shortfall = n - len(chosen)
    if shortfall:
        leftovers = [key for key in pool["contradicts"] + pool["mencion"] if key not in chosen]
        chosen += rng.sample(leftovers, shortfall)
    order = {key: pos for pos, key in enumerate(by_claim)}
    return [(eid, i, by_claim[(eid, i)]) for eid, i in sorted(chosen, key=order.__getitem__)]


def sample_claims(
    n: int = 10,
    seed: int = 42,
    *,
    syntheses: Mapping[str, Synthesis],
    retrievals: Mapping[str, RetrievalRecord],
    excavador_storage: PaperLookup,
    contradicts_quota: int = DEFAULT_CONTRADICTS_QUOTA,
    mention_quota: int = DEFAULT_MENTION_QUOTA,
    mention_ids: Sequence[str] | None = None,
    primary_works: Mapping[str, PrimaryWork] = PRIMARY_WORKS,
) -> list[SampledClaim]:
    """Muestra estratificada (`select_claims`) con el texto de cada chunk y los metadatos de su paper."""
    chunks = _chunk_index(retrievals)
    sampled = []
    for eid, index, stratum in select_claims(syntheses, n, seed, contradicts_quota, mention_quota, mention_ids):
        s = syntheses[eid]
        claim = s.key_claims[index]
        review_chunks = []
        for chunk_id in claim.supporting_chunks:
            entry = chunks.get(chunk_id)
            if entry is None:
                raise ValueError(f"{claim_id(eid, index)}: {chunk_id} no está en ningún _retrieval/")
            chunk = entry["chunk"]
            paper = excavador_storage.get_paper(chunk.paper_id)
            if paper is None:
                raise ValueError(f"{chunk.paper_id} no está en excavador.db")
            review_chunks.append(
                ReviewChunk(
                    chunk_id=chunk_id,
                    paper_id=chunk.paper_id,
                    title=paper.title,
                    authors=list(paper.authors),
                    year=int(paper.year),
                    from_abstract=bool(entry["from_abstract"]),
                    primary_work=primary_works.get(chunk.paper_id),
                    text=_clean(chunk.text),
                )
            )
        key = _thesis_key(claim.text)
        twins = [
            IndexedClaim(index=j, claim=other)
            for j, other in enumerate(s.key_claims)
            if j != index and other.stance != claim.stance and _thesis_key(other.text) == key
        ]
        sampled.append(
            SampledClaim(
                expert_id=eid, claim_index=index, stratum=stratum, synthesis_id=s.synthesis_id, claim=claim, chunks=review_chunks, twins=twins
            )
        )
    return sampled


def population_by_stance(syntheses: Mapping[str, Synthesis]) -> dict[str, int]:
    counts = Counter(c.stance for s in syntheses.values() for c in s.key_claims)
    return {stance: counts.get(stance, 0) for stance in STANCES}


# --- Mención de pasada y concentración de fuentes (sin LLM) ----------------------------

# Verbos o giros que, en el texto de una claim, sugieren que el pasaje solo nombra la idea.
# «fuerte»: casi siempre mención; «débil»: también introduce exposiciones de verdad.
MENTION_MARKERS: dict[str, tuple[str, ...]] = {
    "fuerte": (
        r"\bmencion\w*",
        r"\balud\w*",
        r"\balusi[oó]n\w*",
        r"\bde pasada\b",
        r"\bnombra\w*",
        r"\bse refiere\w*|\brefiere\w*",
        r"\bcita\w*\b",
        r"\brecuerda\w*",
        r"\brese[ñn]a\w*",
        r"\bevoca\w*",
        r"\bautores como\b",
    ),
    "débil": (r"\bseñala\w*", r"\bindica\w*", r"\bpresenta\w*", r"\bdestaca\w*"),
}


class MentionCandidate(BaseModel):
    claim_id: str
    stance: str
    strength: Literal["fuerte", "débil"]
    markers: list[str]
    n_chunks: int
    text: str


def mention_candidates(syntheses: Mapping[str, Synthesis], stance: str | None = "supports") -> list[MentionCandidate]:
    """Claims (`stance`, todas si es None) cuyo texto contiene un marcador de mención.

    Heurística léxica: la regla de atribución de N8 obliga a escribir «X sostiene/expone…», así
    que la ausencia de marcadores no prueba que no haya menciones de pasada. Sirve para apuntar
    dónde leer, no para contar. El paréntesis final de autores no se mira: «(pasaje de X, que cita
    a Echeverría)» describe el pasaje, no la claim (falso positivo de C4#4 en N10).
    """
    found = []
    for eid, index, claim in _claim_pool(syntheses):
        if stance is not None and claim.stance != stance:
            continue
        text = _strip_authors(claim.text).lower()
        for strength, patterns in MENTION_MARKERS.items():
            markers = sorted({m.group(0) for p in patterns for m in re.finditer(p, text)})
            if markers:
                found.append(
                    MentionCandidate(
                        claim_id=claim_id(eid, index),
                        stance=claim.stance,
                        strength=strength,
                        markers=markers,
                        n_chunks=len(claim.supporting_chunks),
                        text=claim.text,
                    )
                )
                break
    return found


class SourceConcentration(BaseModel):
    expert_id: str
    n_claims: int
    top_paper_id: str
    top_title: str
    n_top: int  # claims que citan al menos un chunk de ese paper
    share: float
    n_papers_cited: int


def source_concentration(
    syntheses: Mapping[str, Synthesis], retrievals: Mapping[str, RetrievalRecord], excavador_storage: PaperLookup
) -> list[SourceConcentration]:
    """Por clúster, el paper que sustenta más claims y su porcentaje. Una claim cuenta una vez por paper."""
    chunk_paper = {chunk_id: entry["chunk"].paper_id for chunk_id, entry in _chunk_index(retrievals).items()}
    rows = []
    for eid in sorted(syntheses, key=_expert_order):
        claims = syntheses[eid].key_claims
        per_paper: Counter[str] = Counter()
        for claim in claims:
            try:
                papers = {chunk_paper[chunk_id] for chunk_id in claim.supporting_chunks}
            except KeyError as exc:
                raise ValueError(f"{eid}: {exc.args[0]} no está en ningún _retrieval/") from exc
            per_paper.update(papers)
        if not claims:
            continue
        top_paper_id, n_top = min(per_paper.items(), key=lambda item: (-item[1], item[0]))
        paper = excavador_storage.get_paper(top_paper_id)
        rows.append(
            SourceConcentration(
                expert_id=eid,
                n_claims=len(claims),
                top_paper_id=top_paper_id,
                top_title=paper.title if paper else "?",
                n_top=n_top,
                share=n_top / len(claims),
                n_papers_cited=len(per_paper),
            )
        )
    return rows


# --- Documento de revisión y veredictos ----------------------------------------------

_VERDICT_BLOCK_RE = re.compile(r"^```veredicto\n(.*?)^```", re.DOTALL | re.MULTILINE)


def _wrap(text: str, width: int = 100) -> str:
    return textwrap.fill(text, width=width, break_long_words=False, break_on_hyphens=False)


def _source_line(chunk: ReviewChunk) -> str:
    authors = "; ".join(chunk.authors) or "desconocido"
    source = "abstract (`from_abstract`)" if chunk.from_abstract else "PDF"
    line = f"- **{chunk.title}** · {authors} · {chunk.year} · fuente: {source} · `{chunk.paper_id}`"
    if chunk.primary_work:
        line += (
            f"\n- ⚠ **PRIMARY_WORKS** (A17): autor real **{chunk.primary_work.real_author}**. "
            f"{chunk.primary_work.attribution_note}"
        )
    return line


def render_review(
    sampled: Sequence[SampledClaim],
    *,
    seed: int,
    population: Mapping[str, int],  # claims por estrato
    mentions: Sequence[MentionCandidate] = (),
    concentration: Sequence[SourceConcentration] = (),
    created_at: datetime | None = None,
) -> str:
    created_at = created_at or datetime.now(timezone.utc)
    by_stratum = Counter(s.stratum for s in sampled)
    lines = [
        "# N10 · Muestra de claims para revisión manual",
        "",
        f"Generado {created_at:%Y-%m-%d %H:%M} UTC · semilla {seed} · n = {len(sampled)}",
        "",
        "| estrato | población | muestra | qué es |",
        "|---|---|---|---|",
        f"| `corriente` | {population.get('corriente', 0)} | {by_stratum.get('corriente', 0)} | el resto, al azar |",
        f"| `mencion` | {population.get('mencion', 0)} | {by_stratum.get('mencion', 0)} | "
        "`supports` con marcador fuerte de mención de pasada (anexo A), elegidas leyendo |",
        f"| `contradicts` | {population.get('contradicts', 0)} | {by_stratum.get('contradicts', 0)} | "
        "estrato raro (A19), al azar |",
        "",
        "Criterio 3 de la spec 04: ≥ 9 de 10 claims realmente sustentadas por su pasaje. La muestra se inclina a",
        "propósito hacia los estratos raros, así que el criterio se juzga por la tasa **ponderada** por población",
        "(A23 del registro). Se informan dos tasas: criterio 3 (`ok` / juzgables) y acierto de stance",
        "(`ok` / (`ok` + `stance_erroneo`)). `chunk_roto` no entra en ninguna.",
        "",
        "## Cómo anotar",
        "",
        "Rellena `veredicto:` en el bloque de cada claim con UNO de estos valores, y `nota:` si hace falta",
        "(puede ocupar varias líneas, dentro del bloque). Un veredicto vacío cuenta como pendiente.",
        "",
        *[f"- `{v}`: {VERDICT_HELP[v]}" for v in VERDICTS],
        "",
        "El veredicto es por claim. Si cita varios pasajes y uno está roto pero los otros la sustentan, es `ok`.",
        "El texto de cada pasaje es el que leyó el modelo (limpieza de entidades HTML y espacios, como en el",
        "prompt de N8); viene reajustado a 100 columnas, sin otros cambios.",
        "",
        "Luego: `python -m expertos sample --report`.",
    ]
    for pos, s in enumerate(sampled, 1):
        lines += [
            "",
            "---",
            "",
            f"## {pos} · {s.claim_id} — `{s.claim.stance}` · estrato `{s.stratum}`",
            "",
            f"Síntesis `{s.synthesis_id}` · {len(s.chunks)} pasaje(s)",
            "",
            f"> {s.claim.text}",
        ]
        for twin in s.twins:
            lines += [
                "",
                f"Tesis gemela (A19): **{claim_id(s.expert_id, twin.index)}** — `{twin.claim.stance}`, "
                f"cita {', '.join(f'`{c}`' for c in twin.claim.supporting_chunks)}",
                "",
                f"> {twin.claim.text}",
            ]
        for chunk in s.chunks:
            lines += ["", f"### `{chunk.chunk_id}`", "", _source_line(chunk), "", "```text", _wrap(chunk.text), "```"]
        lines += [
            "",
            "```veredicto",
            f"claim: {s.claim_id}",
            f"stance: {s.claim.stance}",
            f"estrato: {s.stratum}",
            "veredicto:",
            "nota:",
            "```",
        ]
    if mentions:
        lines += [
            "",
            "---",
            "",
            "## Anexo A · Claims `supports` con marcadores de mención (heurística léxica)",
            "",
            "No consume LLM. La regla de atribución de N8 obliga a escribir «X sostiene/expone…», así que la",
            "falta de marcadores no descarta menciones de pasada. «débil» = verbo que también introduce",
            "exposiciones de verdad.",
            "",
            "| claim | fuerza | marcadores | chunks | texto |",
            "|---|---|---|---|---|",
            *[
                f"| {m.claim_id} | {m.strength} | {', '.join(m.markers)} | {m.n_chunks} | {m.text.replace('|', '/')} |"
                for m in mentions
            ],
        ]
    if concentration:
        lines += [
            "",
            "---",
            "",
            "## Anexo B · Concentración de fuentes por clúster",
            "",
            "Porcentaje de claims que citan al menos un chunk del paper más citado del clúster.",
            "",
            "| clúster | claims | papers citados | % del más citado | paper más citado |",
            "|---|---|---|---|---|",
            *[
                f"| {c.expert_id} | {c.n_claims} | {c.n_papers_cited} | {c.n_top}/{c.n_claims} = {c.share:.0%} | "
                f"{c.top_title.replace('|', '/')} (`{c.top_paper_id}`) |"
                for c in sorted(concentration, key=lambda c: -c.share)
            ],
        ]
    return "\n".join(lines) + "\n"


def dump_for_review(sampled: Sequence[SampledClaim], out_path: Path, **render_kwargs) -> Path:
    """Escribe el `.md` de revisión (atómico) con un bloque `veredicto` vacío por claim."""
    _atomic_write_text(Path(out_path), render_review(sampled, **render_kwargs))
    return Path(out_path)


class Verdict(BaseModel):
    claim_id: str
    stance: str
    stratum: str
    verdict: VerdictLabel | None  # None = pendiente
    note: str | None


def parse_verdicts(text: str) -> list[Verdict]:
    """Lee los bloques ```veredicto de un `.md` de revisión. Un valor desconocido es error, no pendiente."""
    verdicts = []
    for match in _VERDICT_BLOCK_RE.finditer(text):
        fields: dict[str, str] = {}
        current = None
        for raw in match.group(1).splitlines():
            key, sep, value = raw.partition(":")
            if sep and key.strip() in ("claim", "stance", "estrato", "veredicto", "nota"):
                current = key.strip()
                fields[current] = value.strip()
            elif current == "nota":
                fields["nota"] = (fields["nota"] + "\n" + raw.strip()).strip()
        if "claim" not in fields:
            raise ValueError(f"bloque veredicto sin `claim:`: {match.group(0)[:80]!r}")
        value = fields.get("veredicto", "").strip().strip("`").lower() or None
        if value is not None and value not in VERDICTS:
            raise ValueError(f"{fields['claim']}: veredicto {value!r} no es uno de {', '.join(VERDICTS)}")
        verdicts.append(
            Verdict(
                claim_id=fields["claim"],
                stance=fields.get("stance", ""),
                stratum=fields.get("estrato") or fields.get("stance", ""),
                verdict=value,
                note=fields.get("nota") or None,
            )
        )
    return verdicts


def load_verdicts(path: Path) -> list[Verdict]:
    return parse_verdicts(Path(path).read_text(encoding="utf-8"))


class ReviewSummary(BaseModel):
    """Resumen de los veredictos. Juzgables = `ok` + `claim_infiel` + `stance_erroneo` (sin `chunk_roto` ni pendientes)."""

    n: int
    n_pending: int
    counts: dict[str, int]  # por veredicto
    counts_by_stratum: dict[str, dict[str, int]]
    n_judgeable: int
    support_rate: float | None  # criterio 3, cruda: ok / juzgables
    weighted_support_rate: float | None  # criterio 3, ponderada por población: la que decide
    stance_rate: float | None  # acierto de stance, cruda: ok / (ok + stance_erroneo)
    weighted_stance_rate: float | None
    meets_criterion_3: bool | None  # None mientras haya pendientes


def _support_rate(c: Mapping[str, int]) -> float | None:
    judgeable = c.get("ok", 0) + c.get("claim_infiel", 0) + c.get("stance_erroneo", 0)
    return c.get("ok", 0) / judgeable if judgeable else None


def _stance_rate(c: Mapping[str, int]) -> float | None:
    supported_text = c.get("ok", 0) + c.get("stance_erroneo", 0)
    return c.get("ok", 0) / supported_text if supported_text else None


def _weighted(rate_by_stratum: Mapping[str, float | None], population: Mapping[str, int]) -> float | None:
    """Media de las tasas por estrato, ponderada por su población. Un estrato sin juzgables no entra."""
    defined = {st: rate for st, rate in rate_by_stratum.items() if rate is not None and population.get(st, 0)}
    total = sum(population[st] for st in defined)
    return sum(population[st] * rate for st, rate in defined.items()) / total if total else None


def summarize(verdicts: Sequence[Verdict], population: Mapping[str, int] | None = None) -> ReviewSummary:
    """Las dos tasas de N10. `stance_erroneo` NO cuenta como sustentada; `chunk_roto` sale del
    denominador (E6: no cuenta contra el Experto).

    Con `population` (claims por estrato), cada tasa se calcula por estrato y se pondera por su
    población; el criterio 3 se juzga por la ponderada (A23). Sin ella, decide la cruda.
    """
    counts = Counter(v.verdict for v in verdicts if v.verdict)
    by_stratum: dict[str, Counter] = {}
    for v in verdicts:
        if v.verdict:
            by_stratum.setdefault(v.stratum, Counter())[v.verdict] += 1
    weighted_support = weighted_stance = None
    if population:
        weighted_support = _weighted({st: _support_rate(c) for st, c in by_stratum.items()}, population)
        weighted_stance = _weighted({st: _stance_rate(c) for st, c in by_stratum.items()}, population)
    support = _support_rate(counts)
    n_pending = sum(1 for v in verdicts if v.verdict is None)
    deciding = weighted_support if population else support
    return ReviewSummary(
        n=len(verdicts),
        n_pending=n_pending,
        counts={v: counts.get(v, 0) for v in VERDICTS},
        counts_by_stratum={st: {v: c.get(v, 0) for v in VERDICTS} for st, c in sorted(by_stratum.items())},
        n_judgeable=counts["ok"] + counts["claim_infiel"] + counts["stance_erroneo"],
        support_rate=support,
        weighted_support_rate=weighted_support,
        stance_rate=_stance_rate(counts),
        weighted_stance_rate=weighted_stance,
        meets_criterion_3=None if n_pending or deciding is None else deciding >= CRITERION_3_MIN_RATE,
    )
