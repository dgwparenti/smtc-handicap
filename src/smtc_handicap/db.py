"""SQLite database layer for Cresta Run race data."""

from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path

from smtc_handicap.models import Race, Rider, TimeRecord

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS riders (
    rider_id        TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    nationality     TEXT NOT NULL DEFAULT '',
    is_sl           INTEGER NOT NULL DEFAULT 0,
    is_am           INTEGER NOT NULL DEFAULT 0,
    first_seen_date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS races (
    race_id          TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    date             TEXT NOT NULL,
    start_position   TEXT NOT NULL CHECK (start_position IN ('TOP', 'JUNCTION')),
    is_handicap_race INTEGER NOT NULL DEFAULT 0,
    is_practice      INTEGER NOT NULL DEFAULT 0,
    day_number       INTEGER,
    pdf_source       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS time_records (
    record_id      TEXT PRIMARY KEY,
    race_id        TEXT NOT NULL REFERENCES races(race_id),
    rider_id       TEXT NOT NULL REFERENCES riders(rider_id),
    run_number     INTEGER NOT NULL,
    start_time     TEXT,
    split_junction REAL,
    split_rise     REAL,
    split_stream   REAL,
    split_bulpetts REAL,
    finish_time    REAL,
    speed_mph      REAL,
    handicap       REAL,
    is_fall        INTEGER NOT NULL DEFAULT 0,
    fall_location  TEXT,
    is_dnf         INTEGER NOT NULL DEFAULT 0,
    UNIQUE(race_id, rider_id, run_number)
);

CREATE INDEX IF NOT EXISTS idx_time_records_rider ON time_records(rider_id);
CREATE INDEX IF NOT EXISTS idx_time_records_race  ON time_records(race_id);
CREATE INDEX IF NOT EXISTS idx_races_date         ON races(date);
CREATE INDEX IF NOT EXISTS idx_races_position     ON races(start_position);
CREATE INDEX IF NOT EXISTS idx_time_records_rider_race ON time_records(rider_id, race_id);
"""


class CrestaDB:
    """SQLite database for Cresta Run race data."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()

    def _create_tables(self) -> None:
        self.conn.executescript(SCHEMA_SQL)

    # -- Rider --

    def upsert_rider(self, rider: Rider) -> None:
        """Insert or merge a rider record.

        Merge rules:
        - display_name: keep existing (first-seen is canonical)
        - nationality: update only if existing is empty and new is non-empty
        - is_sl / is_am: OR logic
        - first_seen_date: keep the earlier date
        """
        existing = self.get_rider(rider.rider_id)
        if existing is None:
            self.conn.execute(
                """INSERT INTO riders (rider_id, display_name, nationality,
                   is_sl, is_am, first_seen_date)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    rider.rider_id,
                    rider.display_name,
                    rider.nationality,
                    int(rider.is_sl),
                    int(rider.is_am),
                    rider.first_seen_date.isoformat(),
                ),
            )
        else:
            nationality = existing.nationality if existing.nationality else rider.nationality
            is_sl = existing.is_sl or rider.is_sl
            is_am = existing.is_am or rider.is_am
            first_seen = min(existing.first_seen_date, rider.first_seen_date)
            self.conn.execute(
                """UPDATE riders SET nationality=?, is_sl=?, is_am=?, first_seen_date=?
                   WHERE rider_id=?""",
                (nationality, int(is_sl), int(is_am), first_seen.isoformat(), rider.rider_id),
            )
        self.conn.commit()

    def get_rider(self, rider_id: str) -> Rider | None:
        row = self.conn.execute(
            "SELECT rider_id, display_name, nationality, is_sl, is_am, first_seen_date "
            "FROM riders WHERE rider_id=?",
            (rider_id,),
        ).fetchone()
        if row is None:
            return None
        return Rider(
            rider_id=row[0],
            display_name=row[1],
            nationality=row[2],
            is_sl=bool(row[3]),
            is_am=bool(row[4]),
            first_seen_date=datetime.date.fromisoformat(row[5]),
        )

    def get_all_riders(self) -> list[Rider]:
        rows = self.conn.execute(
            "SELECT rider_id, display_name, nationality, is_sl, is_am, first_seen_date "
            "FROM riders ORDER BY rider_id"
        ).fetchall()
        return [
            Rider(
                rider_id=r[0],
                display_name=r[1],
                nationality=r[2],
                is_sl=bool(r[3]),
                is_am=bool(r[4]),
                first_seen_date=datetime.date.fromisoformat(r[5]),
            )
            for r in rows
        ]

    # -- Race --

    def insert_race(self, race: Race) -> None:
        """Insert a race (silently ignores duplicates)."""
        self.conn.execute(
            """INSERT OR IGNORE INTO races
               (race_id, name, date, start_position, is_handicap_race,
                is_practice, day_number, pdf_source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                race.race_id,
                race.name,
                race.date.isoformat(),
                race.start_position,
                int(race.is_handicap_race),
                int(race.is_practice),
                race.day_number,
                race.pdf_source,
            ),
        )
        self.conn.commit()

    def get_race(self, race_id: str) -> Race | None:
        row = self.conn.execute(
            "SELECT race_id, name, date, start_position, is_handicap_race, "
            "is_practice, day_number, pdf_source FROM races WHERE race_id=?",
            (race_id,),
        ).fetchone()
        if row is None:
            return None
        return Race(
            race_id=row[0],
            name=row[1],
            date=datetime.date.fromisoformat(row[2]),
            start_position=row[3],
            is_handicap_race=bool(row[4]),
            is_practice=bool(row[5]),
            day_number=row[6],
            pdf_source=row[7],
        )

    def race_exists(self, race_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM races WHERE race_id=?", (race_id,)
        ).fetchone()
        return row is not None

    # -- TimeRecord --

    def insert_time_record(self, record: TimeRecord) -> None:
        """Insert a time record (silently ignores duplicates)."""
        self.conn.execute(
            """INSERT OR IGNORE INTO time_records
               (record_id, race_id, rider_id, run_number, start_time,
                split_junction, split_rise, split_stream, split_bulpetts,
                finish_time, speed_mph, handicap, is_fall, fall_location, is_dnf)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.record_id,
                record.race_id,
                record.rider_id,
                record.run_number,
                record.start_time.isoformat() if record.start_time else None,
                record.split_junction,
                record.split_rise,
                record.split_stream,
                record.split_bulpetts,
                record.finish_time,
                record.speed_mph,
                record.handicap,
                int(record.is_fall),
                record.fall_location,
                int(record.is_dnf),
            ),
        )
        self.conn.commit()

    def get_time_records_for_rider(
        self, rider_id: str, start_position: str | None = None
    ) -> list[TimeRecord]:
        if start_position:
            rows = self.conn.execute(
                """SELECT tr.* FROM time_records tr
                   JOIN races r ON tr.race_id = r.race_id
                   WHERE tr.rider_id=? AND r.start_position=?
                   ORDER BY r.date, tr.run_number""",
                (rider_id, start_position),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM time_records WHERE rider_id=? ORDER BY race_id, run_number",
                (rider_id,),
            ).fetchall()
        return [self._row_to_time_record(r) for r in rows]

    def get_time_records_for_race(self, race_id: str) -> list[TimeRecord]:
        rows = self.conn.execute(
            "SELECT * FROM time_records WHERE race_id=? ORDER BY rider_id, run_number",
            (race_id,),
        ).fetchall()
        return [self._row_to_time_record(r) for r in rows]

    @staticmethod
    def _row_to_time_record(row: tuple) -> TimeRecord:
        return TimeRecord(
            record_id=row[0],
            race_id=row[1],
            rider_id=row[2],
            run_number=row[3],
            start_time=(
                datetime.time.fromisoformat(row[4]) if row[4] else None
            ),
            split_junction=row[5],
            split_rise=row[6],
            split_stream=row[7],
            split_bulpetts=row[8],
            finish_time=row[9],
            speed_mph=row[10],
            handicap=row[11],
            is_fall=bool(row[12]),
            fall_location=row[13],
            is_dnf=bool(row[14]),
        )

    # -- Incremental ingestion helpers --

    def get_max_race_date(self) -> datetime.date | None:
        row = self.conn.execute("SELECT MAX(date) FROM races").fetchone()
        if row and row[0]:
            return datetime.date.fromisoformat(row[0])
        return None

    def get_ingested_pdf_sources(self) -> set[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT pdf_source FROM races WHERE pdf_source != ''"
        ).fetchall()
        return {r[0] for r in rows}

    # -- Row counts --

    def get_counts(self) -> dict[str, int]:
        counts = {}
        for table in ("riders", "races", "time_records"):
            row = self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()  # noqa: S608
            counts[table] = row[0]
        return counts

    # -- Lifecycle --

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> CrestaDB:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
