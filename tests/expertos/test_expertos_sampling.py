"""Tests para expertos.sampling (N10): muestra estratificada, documento de revisión y veredictos."""

from datetime import datetime, timezone

import pytest

from expertos.assignments import PrimaryWork
from expertos.models import Claim, Synthesis
from expertos.sampling import (
    CRITERION_3_MIN_RATE,
    Verdict,
    dump_for_review,
    load_verdicts,
    mention_candidates,
    parse_verdicts,
    population_by_stance,
    population_by_stratum,
    sample_claims,
    select_claims,
    source_concentration,
    strata,
    summarize,
)
from expertos.synthesis import CandidateChunk, RetrievalRecord
from tests.expertos.test_expertos_labeling import _paper
from tests.expertos.test_expertos_synthesis import _chunk

RUN_ID = "kmeans-k9-seed42-0123abcd"
NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)
MARX = "doi:marx"


class Storage:
    def __init__(self, paper_ids) -> None:
        self._papers = {pid: _paper(pid) for pid in paper_ids}

    def get_paper(self, paper_id):
        return self._papers.get(paper_id)


def _corpus(n_clusters: int = 4, per_cluster: int = 12, contradicts_every: int = 7):
    """Síntesis y retrievals sintéticos: 48 claims, con un `contradicts` cada `contradicts_every`.

    Cada claim cita un chunk propio; en C0 la mitad de las claims citan además el paper `doi:c0-top`.
    En C2, las claims 1–4 llevan un marcador fuerte de mención: C2#1–#3 son `supports` (estrato
    `mencion`) y C2#4 es `contradicts` (su estrato manda). Estratos: 38 corriente, 3 mencion, 7 contradicts.
    """
    syntheses, retrievals = {}, {}
    k = 0
    for c in range(n_clusters):
        eid = f"C{c}"
        candidates, claims = [], []
        for i in range(per_cluster):
            paper_id = MARX if (c, i) == (1, 0) else f"doi:{eid}-{i}"
            chunk = _chunk(paper_id, i, f"Pasaje {eid}-{i}.")
            candidates.append(CandidateChunk(chunk=chunk, score=0.85, from_abstract=i % 2 == 1, queries=["q"]))
            chunks = [chunk.chunk_id]
            if c == 0 and i % 2 == 0:
                top = _chunk("doi:c0-top", 100 + i, "Pasaje del paper dominante.")
                candidates.append(CandidateChunk(chunk=top, score=0.84, from_abstract=False, queries=["q"]))
                chunks.append(top.chunk_id)
            stance = "contradicts" if k % contradicts_every == 0 else "supports"
            verb = "menciona" if c == 2 and 1 <= i <= 4 else "sostiene"
            claims.append(Claim(text=f"Autora {verb} la tesis {eid}-{i} (autor {i}).", supporting_chunks=chunks, stance=stance))
            k += 1
        syntheses[eid] = Synthesis(
            synthesis_id=f"{RUN_ID}/{eid}/x",
            expert_id=eid,
            topic_label="tema",
            summary=" ".join(["palabra"] * 320),
            key_claims=claims,
            paper_ids=sorted({cc.chunk.paper_id for cc in candidates}),
            updated_at=NOW,
        )
        retrievals[eid] = RetrievalRecord(
            expert_id=eid,
            run_id=RUN_ID,
            created_at=NOW,
            llm_provider="dummy",
            llm_model="dummy",
            topic_label="tema",
            paper_ids=syntheses[eid].paper_ids,
            top_k=8,
            queries=["q"],
            candidates=candidates,
        )
    storage = Storage({cc.chunk.paper_id for r in retrievals.values() for cc in r.candidates})
    return syntheses, retrievals, storage


def _sample(**kwargs):
    syntheses, retrievals, storage = _corpus()
    primary = {MARX: PrimaryWork(real_author="Karl Marx", attribution_note="Texto de Marx.")}
    return sample_claims(
        syntheses=syntheses, retrievals=retrievals, excavador_storage=storage, primary_works=primary, **kwargs
    )


def test_same_seed_same_sample_and_other_seed_differs():
    syntheses, _, _ = _corpus()
    first = select_claims(syntheses, n=10, seed=42)
    assert first == select_claims(syntheses, n=10, seed=42)
    assert len({(eid, i) for eid, i, _ in first}) == 10
    assert first != select_claims(syntheses, n=10, seed=7)


def test_strata_are_disjoint_and_counted():
    syntheses, _, _ = _corpus()
    assert population_by_stratum(syntheses) == {"corriente": 38, "mencion": 3, "contradicts": 7}
    by_claim = strata(syntheses)
    assert by_claim[("C2", 1)] == "mencion" and by_claim[("C2", 4)] == "contradicts"


def test_stratification_puts_contradicts_and_mentions_in():
    syntheses, _, _ = _corpus()
    by_claim = strata(syntheses)
    contra = {key for key, st in by_claim.items() if st == "contradicts"}
    for seed in range(20):  # uniforme, ~20 % de las muestras no traería ningún contradicts
        chosen = select_claims(syntheses, n=10, seed=seed)
        assert [st for *_, st in chosen].count("contradicts") == 3
        assert [st for *_, st in chosen].count("mencion") == 3
        assert all(by_claim[(eid, i)] == st for eid, i, st in chosen)
    assert contra <= {(eid, i) for eid, i, _ in select_claims(syntheses, n=10, seed=42, contradicts_quota=7)}


def test_mention_ids_pick_the_stratum_by_hand():
    syntheses, _, _ = _corpus()
    chosen = select_claims(syntheses, n=10, seed=42, mention_ids=["C2#3", "C2#1"])
    assert [(eid, i) for eid, i, st in chosen if st == "mencion"] == [("C2", 1), ("C2", 3)]
    assert len(chosen) == 10
    # mismos contradicts que el sorteo sin ids: los ids no consumen azar
    contra = [c for c in chosen if c[2] == "contradicts"]
    assert contra == [c for c in select_claims(syntheses, n=10, seed=42) if c[2] == "contradicts"]
    with pytest.raises(ValueError, match="C0#5 no es candidata"):
        select_claims(syntheses, mention_ids=["C0#5"])


def test_quota_larger_than_stratum_and_shortfall():
    syntheses, _, _ = _corpus(n_clusters=1, per_cluster=5, contradicts_every=1)  # todas contradicts
    assert len(select_claims(syntheses, n=5, seed=1, contradicts_quota=2)) == 5
    with pytest.raises(ValueError, match="solo hay 5"):
        select_claims(syntheses, n=6)


def test_sample_carries_chunk_text_metadata_and_primary_work():
    sampled = _sample(n=48, seed=0)  # la población entera
    by_id = {s.claim_id: s for s in sampled}
    marx = by_id["C1#0"].chunks[0]
    assert marx.primary_work.real_author == "Karl Marx"
    assert marx.text == "Pasaje C1-0."
    assert by_id["C0#1"].chunks[0].from_abstract is True
    assert [c.chunk_id for c in by_id["C0#0"].chunks] == by_id["C0#0"].claim.supporting_chunks


def test_twins_pair_same_thesis_with_other_stance():
    syntheses, retrievals, storage = _corpus(n_clusters=1, per_cluster=2, contradicts_every=99)
    s = syntheses["C0"]
    s.key_claims[0] = s.key_claims[0].model_copy(update={"stance": "supports"})
    s.key_claims[1] = Claim(
        text="Autora sostiene la tesis C0-0 (pasajes de Otro).", supporting_chunks=s.key_claims[1].supporting_chunks, stance="contradicts"
    )
    sampled = sample_claims(2, 0, syntheses=syntheses, retrievals=retrievals, excavador_storage=storage)
    assert [t.index for t in sampled[0].twins] == [1]
    assert [t.index for t in sampled[1].twins] == [0]


def test_dump_and_load_verdicts_round_trip(tmp_path):
    sampled = _sample(n=10, seed=42)
    out = dump_for_review(sampled, tmp_path / "r" / "muestra.md", seed=42, population={"corriente": 38})
    text = out.read_text(encoding="utf-8")
    assert "PRIMARY_WORKS" in text or all(not c.primary_work for s in sampled for c in s.chunks)
    pending = load_verdicts(out)
    assert [v.claim_id for v in pending] == [s.claim_id for s in sampled]
    assert [v.stance for v in pending] == [s.claim.stance for s in sampled]
    assert [v.stratum for v in pending] == [s.stratum for s in sampled]
    assert "estrato `mencion`" in text
    assert all(v.verdict is None and v.note is None for v in pending)

    answers = ["ok", "claim_infiel", "chunk_roto", "stance_erroneo", "ok", "ok", "ok", "ok", "ok", "`ok`"]
    filled = text
    for answer in answers:
        filled = filled.replace("veredicto:\nnota:", f"veredicto: {answer}\nnota: primera línea\nsegunda línea", 1)
    out.write_text(filled, encoding="utf-8")
    verdicts = load_verdicts(out)
    assert [v.verdict for v in verdicts] == [a.strip("`") for a in answers]
    assert verdicts[0].note == "primera línea\nsegunda línea"


def test_unknown_verdict_is_an_error(tmp_path):
    out = dump_for_review(_sample(n=2, seed=1), tmp_path / "m.md", seed=1, population={})
    out.write_text(out.read_text(encoding="utf-8").replace("veredicto:\nnota:", "veredicto: sí\nnota:", 1), encoding="utf-8")
    with pytest.raises(ValueError, match="'sí'"):
        load_verdicts(out)


def _v(verdict, stratum="corriente"):
    return Verdict(claim_id="C0#0", stance="supports", stratum=stratum, verdict=verdict, note=None)


def test_verdict_block_without_stratum_falls_back_to_stance():
    [v] = parse_verdicts("```veredicto\nclaim: C1#2\nstance: contradicts\nveredicto: ok\nnota:\n```\n")
    assert v.stratum == "contradicts"


def test_summary_two_rates_stance_errors_are_not_supported():
    verdicts = [_v("ok")] * 6 + [_v("stance_erroneo"), _v("claim_infiel"), _v("chunk_roto"), _v("chunk_roto")]
    s = summarize(verdicts)
    assert s.n == 10 and s.n_pending == 0 and s.n_judgeable == 8
    assert s.counts == {"ok": 6, "claim_infiel": 1, "chunk_roto": 2, "stance_erroneo": 1}
    assert s.support_rate == pytest.approx(6 / 8)  # stance_erroneo no cuenta como sustentada
    assert s.stance_rate == pytest.approx(6 / 7)  # de las que el pasaje sí respalda
    assert s.weighted_support_rate is None and s.weighted_stance_rate is None
    assert s.meets_criterion_3 is False


def test_summary_criterion_pending_and_met():
    assert summarize([_v("ok")] * 9 + [_v(None)]).meets_criterion_3 is None
    s = summarize([_v("ok")] * 9 + [_v("claim_infiel")])
    assert s.support_rate == pytest.approx(CRITERION_3_MIN_RATE) and s.meets_criterion_3 is True
    assert s.stance_rate == 1.0


def test_summary_weights_strata_by_population_and_criterion_uses_weighted():
    # corriente 4/4 ok · mencion: 1 ok, 2 stance_erroneo · contradicts: 1 ok, 1 infiel, 1 roto.
    verdicts = (
        [_v("ok")] * 4
        + [_v("ok", "mencion")] + [_v("stance_erroneo", "mencion")] * 2
        + [_v("ok", "contradicts"), _v("claim_infiel", "contradicts"), _v("chunk_roto", "contradicts")]
    )
    population = {"corriente": 116, "mencion": 5, "contradicts": 7}
    s = summarize(verdicts, population)
    assert s.support_rate == pytest.approx(6 / 9)  # cruda: no cumpliría
    assert s.weighted_support_rate == pytest.approx((116 * 1 + 5 / 3 + 7 / 2) / 128)
    assert s.stance_rate == pytest.approx(6 / 8)
    assert s.weighted_stance_rate == pytest.approx((116 * 1 + 5 / 3 + 7 * 1) / 128)
    assert s.counts_by_stratum["mencion"] == {"ok": 1, "claim_infiel": 0, "chunk_roto": 0, "stance_erroneo": 2}
    assert s.meets_criterion_3 is True  # ≈ 95 % ponderada (A23)


def test_population_by_stance():
    syntheses, _, _ = _corpus()
    assert population_by_stance(syntheses) == {"supports": 41, "contradicts": 7, "mentions": 0}


def test_mention_candidates_only_supports_with_markers():
    syntheses, _, _ = _corpus(n_clusters=1, per_cluster=4, contradicts_every=99)
    claims = syntheses["C0"].key_claims
    for i, text in enumerate(
        ["Ana menciona de pasada la tesis.", "Bea señala que la tesis vale.", "Ana sostiene la tesis.", "Ana alude a T."]
    ):
        claims[i] = Claim(text=text, supporting_chunks=claims[i].supporting_chunks, stance="contradicts" if i == 3 else "supports")
    claims.append(
        Claim(text="Ana sostiene T (pasaje de Bea, que cita a Echeverría).", supporting_chunks=claims[0].supporting_chunks, stance="supports")
    )
    found = {m.claim_id: m for m in mention_candidates(syntheses)}
    assert set(found) == {"C0#0", "C0#1"}
    assert found["C0#0"].strength == "fuerte" and found["C0#0"].markers == ["de pasada", "menciona"]
    assert found["C0#1"].strength == "débil"
    assert "C0#3" in {m.claim_id for m in mention_candidates(syntheses, stance=None)}


def test_source_concentration_counts_claims_per_top_paper():
    syntheses, retrievals, storage = _corpus()
    rows = {r.expert_id: r for r in source_concentration(syntheses, retrievals, storage)}
    assert rows["C0"].top_paper_id == "doi:c0-top"
    assert rows["C0"].n_top == 6 and rows["C0"].share == pytest.approx(0.5)
    assert rows["C0"].n_papers_cited == 13
    assert rows["C1"].n_top == 1
