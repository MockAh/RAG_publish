"""Tests para expertos.synthesis_map (N11: mapa C4 y criterio 5)."""

from datetime import datetime, timezone

import pytest

from expertos.labeling import ClusterLabel
from expertos.models import Claim, Synthesis, SynthesisMap
from expertos.persistence import load_synthesis_map, save_synthesis_map
from expertos.synthesis_map import (
    SynthesisMapError,
    build_synthesis_map,
    count_map_tokens,
    map_text,
)

RUN_ID = "kmeans-k9-seed42-abcd1234"
NOW = datetime(2026, 11, 3, tzinfo=timezone.utc)


def _synthesis(expert_id: str, paper_ids: list[str], label: str | None = None, run_id: str = RUN_ID) -> Synthesis:
    return Synthesis(
        synthesis_id=f"{run_id}/{expert_id}/20261103T000000Z",
        expert_id=expert_id,
        topic_label=label or f"Tema {expert_id}",
        summary=" ".join(["palabra"] * 300),
        key_claims=[Claim(text="Una claim.", supporting_chunks=["p#0"], stance="supports")],
        paper_ids=paper_ids,
        updated_at=NOW,
    )


def _label(expert_id: str) -> ClusterLabel:
    return ClusterLabel(
        topic_label=f"Tema {expert_id}",
        one_liner=f"Permite responder preguntas sobre {expert_id}.",
        keywords=["uno", "dos"],
        coherent=True,
        note=None,
    )


@pytest.fixture
def sources():
    assignment = {"a": "C0", "b": "C0", "c": "C10", "d": "C2"}
    syntheses = {
        "C0": _synthesis("C0", ["a", "b"]),
        "C2": _synthesis("C2", ["d"]),
        "C10": _synthesis("C10", ["c"]),
    }
    labels = {e: _label(e) for e in syntheses}
    return syntheses, labels, assignment


def test_entries_combine_sources_in_numeric_order(sources):
    syntheses, labels, assignment = sources
    m = build_synthesis_map(RUN_ID, syntheses, labels, assignment, updated_at=NOW)
    assert [e.expert_id for e in m.entries] == ["C0", "C2", "C10"]  # no lexicográfico
    first = m.entries[0]
    assert (first.topic_label, first.n_papers) == ("Tema C0", 2)
    assert first.one_liner == "Permite responder preguntas sobre C0."
    assert first.keywords == ["uno", "dos"]
    assert (m.run_id, m.updated_at) == (RUN_ID, NOW)


def test_missing_synthesis_is_an_error(sources):
    syntheses, labels, assignment = sources
    del syntheses["C2"]
    with pytest.raises(SynthesisMapError, match=r"síntesis: faltan \['C2'\]"):
        build_synthesis_map(RUN_ID, syntheses, labels, assignment)


def test_extra_label_is_an_error(sources):
    syntheses, labels, assignment = sources
    labels["C99"] = _label("C99")
    with pytest.raises(SynthesisMapError, match=r"etiquetas: faltan \[\], sobran \['C99'\]"):
        build_synthesis_map(RUN_ID, syntheses, labels, assignment)


def test_synthesis_from_other_run_is_an_error(sources):
    syntheses, labels, assignment = sources
    syntheses["C2"] = _synthesis("C2", ["d"], run_id="kmeans-k8-seed42-00000000")
    with pytest.raises(SynthesisMapError, match="C2: la síntesis .* no es de"):
        build_synthesis_map(RUN_ID, syntheses, labels, assignment)


@pytest.mark.parametrize("paper_ids", [["a"], ["a", "b", "z"], ["a", "b", "b"]])
def test_paper_ids_must_match_partition(sources, paper_ids):
    syntheses, labels, assignment = sources
    syntheses["C0"] = _synthesis("C0", paper_ids)
    with pytest.raises(SynthesisMapError, match="C0: los paper_ids"):
        build_synthesis_map(RUN_ID, syntheses, labels, assignment)


def test_topic_label_mismatch_is_an_error(sources):
    syntheses, labels, assignment = sources
    syntheses["C2"] = _synthesis("C2", ["d"], label="Otro tema")
    with pytest.raises(SynthesisMapError, match="C2: topic_label"):
        build_synthesis_map(RUN_ID, syntheses, labels, assignment)


def test_empty_partition_is_an_error():
    with pytest.raises(SynthesisMapError, match="vacía"):
        build_synthesis_map(RUN_ID, {}, {}, {})


def test_all_problems_are_reported_together(sources):
    syntheses, labels, assignment = sources
    del labels["C10"]
    syntheses["C2"] = _synthesis("C2", ["d", "z"])
    with pytest.raises(SynthesisMapError) as exc:
        build_synthesis_map(RUN_ID, syntheses, labels, assignment)
    assert "etiquetas" in str(exc.value) and "C2:" in str(exc.value)


def test_over_token_limit_is_an_error(sources):
    syntheses, labels, assignment = sources
    with pytest.raises(SynthesisMapError, match="criterio 5"):
        build_synthesis_map(RUN_ID, syntheses, labels, assignment, token_limit=10)


def test_token_count_grows_with_utf8_bytes_of_persisted_text(sources):
    syntheses, labels, assignment = sources
    m = build_synthesis_map(RUN_ID, syntheses, labels, assignment, updated_at=NOW)
    n_bytes = len(map_text(m).encode("utf-8"))
    assert count_map_tokens(m) >= n_bytes / 2.5
    longer = m.model_copy(deep=True)
    longer.entries[0].keywords.append("añadiduría")
    assert count_map_tokens(longer) > count_map_tokens(m)


def test_persisted_file_is_the_counted_text_and_round_trips(sources, tmp_path):
    syntheses, labels, assignment = sources
    m = build_synthesis_map(RUN_ID, syntheses, labels, assignment, updated_at=NOW)
    path = save_synthesis_map(m, path=tmp_path / "map.json")
    assert path.read_text(encoding="utf-8") == map_text(m)
    assert load_synthesis_map(path=path) == m
    assert isinstance(load_synthesis_map(path=path), SynthesisMap)
