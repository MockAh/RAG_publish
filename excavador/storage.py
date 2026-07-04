"""Almacenamiento SQLite para PaperRecord y DiscardedRecord.

Tablas: `papers` (espejo de `PaperRecord`, `paper_id` PRIMARY KEY) y
`papers_discarded` (espejo de `DiscardedRecord`). `authors` y
`references_ids` se guardan como JSON text.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from excavador.models import DiscardedRecord, PaperRecord

_PAPER_COLUMNS = (
    "paper_id",
    "doi",
    "title",
    "authors",
    "year",
    "venue",
    "abstract",
    "source_api",
    "work_type",
    "pdf_path",
    "relevance_score",
    "references_ids",
    "ingested_at",
)

_DISCARDED_COLUMNS = _PAPER_COLUMNS + ("discard_reason",)

_CREATE_PAPERS = """
CREATE TABLE IF NOT EXISTS papers (
    paper_id TEXT PRIMARY KEY,
    doi TEXT,
    title TEXT NOT NULL,
    authors TEXT NOT NULL,
    year INTEGER NOT NULL,
    venue TEXT,
    abstract TEXT NOT NULL,
    source_api TEXT NOT NULL,
    work_type TEXT NOT NULL,
    pdf_path TEXT,
    relevance_score REAL NOT NULL,
    references_ids TEXT NOT NULL,
    ingested_at TEXT NOT NULL
)
"""

_CREATE_PAPERS_DISCARDED = """
CREATE TABLE IF NOT EXISTS papers_discarded (
    paper_id TEXT PRIMARY KEY,
    doi TEXT,
    title TEXT NOT NULL,
    authors TEXT NOT NULL,
    year INTEGER NOT NULL,
    venue TEXT,
    abstract TEXT NOT NULL,
    source_api TEXT NOT NULL,
    work_type TEXT NOT NULL,
    pdf_path TEXT,
    relevance_score REAL NOT NULL,
    references_ids TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    discard_reason TEXT NOT NULL
)
"""


def _paper_to_row(p: PaperRecord) -> tuple:
    return (
        p.paper_id,
        p.doi,
        p.title,
        json.dumps(p.authors, ensure_ascii=False),
        p.year,
        p.venue,
        p.abstract,
        p.source_api,
        p.work_type,
        p.pdf_path,
        p.relevance_score,
        json.dumps(p.references_ids, ensure_ascii=False),
        p.ingested_at.isoformat(),
    )


def _row_to_paper(row: sqlite3.Row) -> PaperRecord:
    return PaperRecord(
        paper_id=row["paper_id"],
        doi=row["doi"],
        title=row["title"],
        authors=json.loads(row["authors"]),
        year=row["year"],
        venue=row["venue"],
        abstract=row["abstract"],
        source_api=row["source_api"],
        work_type=row["work_type"],
        pdf_path=row["pdf_path"],
        relevance_score=row["relevance_score"],
        references_ids=json.loads(row["references_ids"]),
        ingested_at=datetime.fromisoformat(row["ingested_at"]),
    )


class Storage:
    """Acceso a la base SQLite de papers aceptados y descartados."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_CREATE_PAPERS)
        self._conn.execute(_CREATE_PAPERS_DISCARDED)
        self._conn.commit()

    def upsert_paper(self, p: PaperRecord) -> None:
        placeholders = ", ".join("?" for _ in _PAPER_COLUMNS)
        columns = ", ".join(_PAPER_COLUMNS)
        self._conn.execute(
            f"INSERT OR REPLACE INTO papers ({columns}) VALUES ({placeholders})",
            _paper_to_row(p),
        )
        self._conn.commit()

    def upsert_discarded(self, d: DiscardedRecord) -> None:
        placeholders = ", ".join("?" for _ in _DISCARDED_COLUMNS)
        columns = ", ".join(_DISCARDED_COLUMNS)
        row = _paper_to_row(d) + (d.discard_reason,)
        self._conn.execute(
            f"INSERT OR REPLACE INTO papers_discarded ({columns}) VALUES ({placeholders})",
            row,
        )
        self._conn.commit()

    def get_paper(self, paper_id: str) -> PaperRecord | None:
        cursor = self._conn.execute(
            "SELECT * FROM papers WHERE paper_id = ?", (paper_id,)
        )
        row = cursor.fetchone()
        return _row_to_paper(row) if row is not None else None

    def all_papers(self) -> list[PaperRecord]:
        cursor = self._conn.execute("SELECT * FROM papers")
        return [_row_to_paper(row) for row in cursor.fetchall()]

    def known_dois(self) -> set[str]:
        cursor = self._conn.execute(
            "SELECT doi FROM papers WHERE doi IS NOT NULL"
        )
        return {row["doi"] for row in cursor.fetchall()}

    def count(self) -> int:
        cursor = self._conn.execute("SELECT COUNT(*) FROM papers")
        return cursor.fetchone()[0]
