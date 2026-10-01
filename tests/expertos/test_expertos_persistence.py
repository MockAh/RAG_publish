"""Tests para expertos.persistence (X5: síntesis y mapa en JSON, escritura atómica)."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import expertos.persistence as persistence
from expertos.models import Claim, Synthesis, SynthesisMap, SynthesisMapEntry
from expertos.persistence import (
    load_all_syntheses,
    load_synthesis,
    load_synthesis_map,
    save_synthesis,
    save_synthesis_map,
)

UPDATED_AT = datetime(2026, 10, 1, 12, 30, tzinfo=timezone.utc)


def _synthesis(expert_id: str = "C3", summary_word: str = "señorío") -> Synthesis:
    return Synthesis(
        synthesis_id=f"{expert_id}-kmeans-k9-seed42-98b2c308",
        expert_id=expert_id,
        topic_label="Ethos barroco, mestizaje cultural y modernidades alternativas",
        summary=" ".join([summary_word] * 320),
        key_claims=[
            Claim(text="El mestizaje es la forma concreta del ethos barroco.", supporting_chunks=["p#abstract#0"], stance="supports")
        ],
        paper_ids=["openalex:W2140093523"],
        updated_at=UPDATED_AT,
    )


def _map(one_liner: str = "Responde sobre ethos barroco y mestizaje en América Latina.") -> SynthesisMap:
    return SynthesisMap(
        run_id="kmeans-k9-seed42-98b2c308",
        updated_at=UPDATED_AT,
        entries=[
            SynthesisMapEntry(
                expert_id="C3",
                topic_label="Ethos barroco, mestizaje cultural",
                one_liner=one_liner,
                n_papers=17,
                keywords=["ethos barroco", "año", "señorío"],
            )
        ],
    )


# --- síntesis -------------------------------------------------------------------


def test_save_and_load_synthesis_round_trip(tmp_path: Path) -> None:
    synthesis_dir = tmp_path / "data" / "synthesis"  # no existe aún: save lo crea

    path = save_synthesis(_synthesis(), synthesis_dir=synthesis_dir)

    assert path == synthesis_dir / "C3.json"
    assert load_synthesis("C3", synthesis_dir=synthesis_dir) == _synthesis()
    text = path.read_text(encoding="utf-8")
    assert "señorío" in text  # UTF-8 legible, sin escapes
    assert json.loads(text)["updated_at"] == "2026-10-01T12:30:00Z"


def test_save_synthesis_replaces_previous(tmp_path: Path) -> None:
    save_synthesis(_synthesis(summary_word="primera"), synthesis_dir=tmp_path)
    save_synthesis(_synthesis(summary_word="segunda"), synthesis_dir=tmp_path)

    assert load_synthesis("C3", synthesis_dir=tmp_path).summary.startswith("segunda")


def test_load_synthesis_of_unknown_expert_returns_none(tmp_path: Path) -> None:
    assert load_synthesis("C99", synthesis_dir=tmp_path) is None
    assert load_synthesis("C0", synthesis_dir=tmp_path / "no-existe") is None


def test_load_all_syntheses(tmp_path: Path) -> None:
    for expert_id in ("C8", "C0", "C3"):
        save_synthesis(_synthesis(expert_id), synthesis_dir=tmp_path)

    syntheses = load_all_syntheses(synthesis_dir=tmp_path)

    assert sorted(syntheses) == ["C0", "C3", "C8"]
    assert syntheses["C8"] == _synthesis("C8")


def test_load_all_syntheses_of_missing_dir_is_empty(tmp_path: Path) -> None:
    assert load_all_syntheses(synthesis_dir=tmp_path / "no-existe") == {}


def test_load_all_syntheses_rejects_file_named_after_another_expert(tmp_path: Path) -> None:
    save_synthesis(_synthesis("C3"), synthesis_dir=tmp_path)
    (tmp_path / "C3.json").rename(tmp_path / "C4.json")

    with pytest.raises(ValueError, match="C4"):
        load_all_syntheses(synthesis_dir=tmp_path)


@pytest.mark.parametrize("expert_id", ["../C3", "sub/C3", ".C3", ""])
def test_expert_id_must_be_a_plain_file_name(tmp_path: Path, expert_id: str) -> None:
    with pytest.raises(ValueError, match="expert_id no válido"):
        load_synthesis(expert_id, synthesis_dir=tmp_path)


# --- mapa -----------------------------------------------------------------------


def test_save_and_load_synthesis_map_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "data" / "synthesis_map.json"

    assert save_synthesis_map(_map(), path=path) == path
    assert load_synthesis_map(path=path) == _map()
    assert "señorío" in path.read_text(encoding="utf-8")


def test_load_synthesis_map_missing_returns_none(tmp_path: Path) -> None:
    assert load_synthesis_map(path=tmp_path / "synthesis_map.json") is None


# --- escritura atómica ----------------------------------------------------------


class _Boom(Exception):
    pass


def _fail_mid_write(monkeypatch: pytest.MonkeyPatch, step: str) -> None:
    """Hace fallar la escritura atómica en `step`, con el temporal ya escrito a medias o entero."""
    if step == "write":
        real_ntf = persistence.tempfile.NamedTemporaryFile

        def half_written(*args, **kwargs):
            handle = real_ntf(*args, **kwargs)
            real_write = handle.write

            def write(text: str) -> int:
                real_write(text[: len(text) // 2])  # medio JSON en disco…
                raise _Boom("disco lleno")  # …y la corrida muere

            handle.write = write
            return handle

        monkeypatch.setattr(persistence.tempfile, "NamedTemporaryFile", half_written)
    elif step == "fsync":
        monkeypatch.setattr(persistence.os, "fsync", lambda fd: (_ for _ in ()).throw(_Boom("fsync")))
    elif step == "replace":
        monkeypatch.setattr(persistence.os, "replace", lambda src, dst: (_ for _ in ()).throw(_Boom("replace")))


@pytest.mark.parametrize("step", ["write", "fsync", "replace"])
def test_failed_synthesis_write_keeps_previous_file_intact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, step: str
) -> None:
    path = save_synthesis(_synthesis(summary_word="anterior"), synthesis_dir=tmp_path)
    before = path.read_bytes()
    _fail_mid_write(monkeypatch, step)

    with pytest.raises(_Boom):
        save_synthesis(_synthesis(summary_word="nueva"), synthesis_dir=tmp_path)

    assert path.read_bytes() == before
    assert load_synthesis("C3", synthesis_dir=tmp_path).summary.startswith("anterior")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["C3.json"]  # ni temporales huérfanos


@pytest.mark.parametrize("step", ["write", "replace"])
def test_failed_first_synthesis_write_leaves_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, step: str
) -> None:
    _fail_mid_write(monkeypatch, step)

    with pytest.raises(_Boom):
        save_synthesis(_synthesis(), synthesis_dir=tmp_path)

    assert list(tmp_path.iterdir()) == []
    assert load_synthesis("C3", synthesis_dir=tmp_path) is None


def test_failed_map_write_keeps_previous_map_intact(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = save_synthesis_map(_map(one_liner="mapa anterior"), path=tmp_path / "synthesis_map.json")
    before = path.read_bytes()
    _fail_mid_write(monkeypatch, "write")

    with pytest.raises(_Boom):
        save_synthesis_map(_map(one_liner="mapa nuevo"), path=path)

    assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["synthesis_map.json"]
