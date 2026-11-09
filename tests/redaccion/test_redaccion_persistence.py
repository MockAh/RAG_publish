"""Tests para redaccion.persistence (auditoría en JSON, escritura atómica)."""

from pathlib import Path

import pytest

import expertos.persistence as expertos_persistence
from redaccion.models import ChunkVerdict, DraftSection, PieceLog, PieceRecord, VerificationReport
from redaccion.persistence import consultation_dir, load_record, save_record

CHUNK = "doi:10.37819/humanrev.v9i2.866#Conclusiones#43"


def _draft(text: str = "El ethos barroco es una estrategia de resistencia [1].") -> DraftSection:
    return DraftSection(text=text, citations={1: [CHUNK]}, unsupported_marked=True)


def _log() -> PieceLog:
    return PieceLog(
        consultation_id="20261107T120000Z-c3a1",
        pieces=[
            PieceRecord(
                index=0,
                cycle=1,
                text="Según Echeverría, la señora Ñuñoa… [1].",
                kind="factual",
                pair_role=None,
                chunk_ids=[CHUNK],
                verdicts=[ChunkVerdict(chunk_id=CHUNK, verdict="ok", reason="lo dice")],
                status="verified",
            )
        ],
    )


def test_consultation_dir(tmp_path: Path) -> None:
    assert consultation_dir(tmp_path, "abc") == tmp_path / "abc"


@pytest.mark.parametrize("bad", ["", ".", "..", ".oculto", "a/b", "../fuera"])
def test_consultation_dir_rejects_non_flat_ids(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError, match="consultation_id"):
        consultation_dir(tmp_path, bad)


@pytest.mark.parametrize(
    ("instance", "name"),
    [(_draft(), "draft.json"), (VerificationReport(passed=True, failures=[]), "report.json"), (_log(), "pieces.json")],
)
def test_save_and_load_round_trip(tmp_path: Path, instance, name: str) -> None:
    path = consultation_dir(tmp_path / "data" / "redaccion", "c1") / name  # no existe aún: save lo crea

    assert save_record(instance, path) == path
    assert load_record(type(instance), path) == instance
    assert "\\u" not in path.read_text(encoding="utf-8")  # UTF-8 sin escapar


def test_save_refuses_to_overwrite_by_default(tmp_path: Path) -> None:
    path = tmp_path / "draft.json"
    save_record(_draft(), path)

    with pytest.raises(FileExistsError):
        save_record(_draft("otro texto [1]."), path)

    assert load_record(DraftSection, path) == _draft()


def test_save_overwrites_when_asked(tmp_path: Path) -> None:
    path = tmp_path / "draft.json"
    save_record(_draft(), path)

    save_record(_draft("otro texto [1]."), path, overwrite=True)

    assert load_record(DraftSection, path).text == "otro texto [1]."


def test_interrupted_write_keeps_previous_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Un fallo a mitad de escritura deja el archivo anterior íntegro y ningún temporal."""
    path = tmp_path / "draft.json"
    save_record(_draft(), path)

    def boom(*args, **kwargs):
        raise OSError("disco lleno")

    monkeypatch.setattr(expertos_persistence.os, "replace", boom)
    with pytest.raises(OSError, match="disco lleno"):
        save_record(_draft("otro texto [1]."), path, overwrite=True)

    assert load_record(DraftSection, path) == _draft()
    assert [p.name for p in tmp_path.iterdir()] == ["draft.json"]
