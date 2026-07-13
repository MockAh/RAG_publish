"""Tests para excavador.__main__ (CLI, T12)."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

import excavador.__main__ as cli_main
from excavador.__main__ import app
from excavador.config import Settings
from excavador.models import DiscardedRecord, PaperRecord
from excavador.storage import Storage

runner = CliRunner()


def _fake_stats():
    from excavador.pipeline import PipelineStats

    return PipelineStats(
        raw_hits=42,
        invalid=3,
        duplicates=5,
        low_relevance=7,
        snowball_raw_hits=11,
        accepted=13,
        with_pdf=9,
        pct_pdf=0.6923,
        pct_doi=0.8,
        duration_s=12.345,
    )


def _isolate_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Aísla `Settings()` del `.env` real del repo (F4): cwd en tmp_path + env explícito."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EXCAVADOR_OPENALEX_MAILTO", "cli-test@example.com")


def _paper(paper_id: str, title: str, year: int, score: float, pdf: str | None, doi: str | None) -> PaperRecord:
    return PaperRecord(
        paper_id=paper_id,
        doi=doi,
        title=title,
        authors=["Autora Uno"],
        year=year,
        venue="Revista X",
        abstract="Resumen.",
        source_api="openalex",
        work_type="article",
        pdf_path=pdf,
        relevance_score=score,
        references_ids=[],
        ingested_at=datetime.now(timezone.utc),
    )


def test_run_invokes_pipeline_and_prints_stats(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`run` construye Settings, llama a pipeline.run con tema/max_papers y muestra las stats."""
    _isolate_env(monkeypatch, tmp_path)

    calls = {}

    def _fake_pipeline_run(tema, max_papers, settings):
        calls["tema"] = tema
        calls["max_papers"] = max_papers
        calls["settings"] = settings
        return _fake_stats()

    monkeypatch.setattr(cli_main, "pipeline_run", _fake_pipeline_run)

    result = runner.invoke(app, ["run", "--tema", "Bolívar Echeverría", "--max-papers", "50"])

    assert result.exit_code == 0
    assert calls["tema"] == "Bolívar Echeverría"
    assert calls["max_papers"] == 50

    output = result.output
    assert "42" in output
    assert "13" in output
    assert "9" in output
    assert "69.2 %" in output
    assert "80.0 %" in output
    assert "12.3 s" in output


def test_run_threshold_overrides_settings_without_mutating(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`--threshold` pisa `relevance_threshold` vía `model_copy`, no muta `Settings`."""
    _isolate_env(monkeypatch, tmp_path)

    captured = {}

    def _fake_pipeline_run(tema, max_papers, settings):
        captured["settings"] = settings
        return _fake_stats()

    monkeypatch.setattr(cli_main, "pipeline_run", _fake_pipeline_run)

    result = runner.invoke(
        app, ["run", "--tema", "tema de prueba", "--threshold", "0.8"]
    )

    assert result.exit_code == 0
    assert captured["settings"].relevance_threshold == 0.8
    # el default de Settings() sigue siendo 0.78: confirma que no se mutó una instancia compartida.
    assert Settings().relevance_threshold == 0.78


def test_stats_shows_totals_title_and_discard_reasons(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`stats` sobre una DB con 2 papers y 1 descartado muestra total, título y motivo."""
    _isolate_env(monkeypatch, tmp_path)
    db_path = tmp_path / "excavador.db"
    monkeypatch.setenv("EXCAVADOR_DB_PATH", str(db_path))

    storage = Storage(db_path)
    storage.upsert_paper(
        _paper("doi:10.1/a", "Un título muy relevante sobre Echeverría", 2020, 0.9, "a.pdf", "10.1/a")
    )
    storage.upsert_paper(
        _paper("doi:10.1/b", "Otro título", 2019, 0.5, None, "10.1/b")
    )
    discarded = DiscardedRecord(
        **_paper("openalex:W1", "Descartado por baja relevancia", 2018, 0.1, None, None).model_dump(),
        discard_reason="low_relevance",
    )
    storage.upsert_discarded(discarded)

    result = runner.invoke(app, ["stats"])

    assert result.exit_code == 0
    assert "Total papers: 2" in result.output
    assert "Un título muy relevante sobre Echeverría" in result.output
    assert "low_relevance: 1" in result.output


def test_stats_missing_db_prints_clean_message(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`stats` sobre una DB inexistente sale limpio (exit 0) con mensaje claro, sin traceback."""
    _isolate_env(monkeypatch, tmp_path)
    monkeypatch.setenv("EXCAVADOR_DB_PATH", str(tmp_path / "no_existe.db"))

    result = runner.invoke(app, ["stats"])

    assert result.exit_code == 0
    assert result.exception is None
    assert "No existe la base de datos" in result.output
