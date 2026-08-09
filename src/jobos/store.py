"""SQLite persistence with an append-only application event trail."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from jobos.domain import Application, Stage

_SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY,
    company TEXT NOT NULL,
    role TEXT NOT NULL,
    source TEXT,
    stage TEXT NOT NULL,
    priority INTEGER NOT NULL,
    applied_on TEXT,
    next_action TEXT,
    next_action_due TEXT,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS application_events (
    id INTEGER PRIMARY KEY,
    application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    from_stage TEXT,
    to_stage TEXT,
    details TEXT NOT NULL DEFAULT '{}',
    happened_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_applications_stage ON applications(stage);
CREATE INDEX IF NOT EXISTS idx_applications_next_action_due ON applications(next_action_due);
CREATE INDEX IF NOT EXISTS idx_application_events_application ON application_events(application_id);
"""


class ConcurrencyError(RuntimeError):
    """Raised when a workflow update was based on a stale application version."""


@dataclass(frozen=True)
class ApplicationEvent:
    id: int
    application_id: int
    event_type: str
    from_stage: Stage | None
    to_stage: Stage | None
    details: dict[str, str]
    happened_at: datetime


class ApplicationStore:
    """A small local database; no account, cloud service, or scrape is required."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(_SCHEMA)

    def create(
        self,
        *,
        company: str,
        role: str,
        source: str | None,
        priority: int,
        notes: str,
    ) -> Application:
        now = _utc_now()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO applications (
                    company, role, source, stage, priority, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    company,
                    role,
                    source,
                    Stage.SAVED.value,
                    priority,
                    notes,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("database did not return the new application ID")
            application_id = int(cursor.lastrowid)
            self._append_event(
                connection,
                application_id=application_id,
                event_type="created",
                from_stage=None,
                to_stage=Stage.SAVED,
                details={},
                happened_at=now,
            )
            return self._get_required(connection, application_id)

    def get(self, application_id: int) -> Application | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM applications WHERE id = ?",
                (application_id,),
            ).fetchone()
        return _application_from_row(row) if row is not None else None

    def list(self, *, stage: Stage | None = None) -> list[Application]:
        query = "SELECT * FROM applications"
        params: tuple[str, ...] = ()
        if stage is not None:
            query += " WHERE stage = ?"
            params = (stage.value,)
        query += (
            " ORDER BY next_action_due IS NULL, next_action_due, priority DESC, updated_at DESC"
        )
        with self._connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_application_from_row(row) for row in rows]

    def transition(
        self,
        *,
        application_id: int,
        target: Stage,
        expected_version: int,
        applied_on: date | None,
    ) -> Application:
        now = _utc_now()
        with self._connection() as connection:
            current = self._get_required(connection, application_id)
            if current.version != expected_version:
                raise ConcurrencyError("application changed; refresh it before changing stages")
            cursor = connection.execute(
                """
                UPDATE applications
                SET stage = ?, applied_on = ?, updated_at = ?, version = version + 1
                WHERE id = ? AND version = ?
                """,
                (
                    target.value,
                    _date_to_storage(applied_on),
                    now.isoformat(),
                    application_id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise ConcurrencyError("application changed; refresh it before changing stages")
            self._append_event(
                connection,
                application_id=application_id,
                event_type="stage_changed",
                from_stage=current.stage,
                to_stage=target,
                details={},
                happened_at=now,
            )
            return self._get_required(connection, application_id)

    def set_next_action(
        self,
        *,
        application_id: int,
        action: str | None,
        due: date | None,
        expected_version: int,
    ) -> Application:
        now = _utc_now()
        with self._connection() as connection:
            current = self._get_required(connection, application_id)
            if current.version != expected_version:
                raise ConcurrencyError(
                    "application changed; refresh it before planning the next action"
                )
            cursor = connection.execute(
                """
                UPDATE applications
                SET next_action = ?, next_action_due = ?, updated_at = ?, version = version + 1
                WHERE id = ? AND version = ?
                """,
                (action, _date_to_storage(due), now.isoformat(), application_id, expected_version),
            )
            if cursor.rowcount != 1:
                raise ConcurrencyError(
                    "application changed; refresh it before planning the next action"
                )
            self._append_event(
                connection,
                application_id=application_id,
                event_type="next_action_changed",
                from_stage=current.stage,
                to_stage=current.stage,
                details={"action": action or "", "due": due.isoformat() if due else ""},
                happened_at=now,
            )
            return self._get_required(connection, application_id)

    def events(self, application_id: int) -> list[ApplicationEvent]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM application_events
                WHERE application_id = ?
                ORDER BY id
                """,
                (application_id,),
            ).fetchall()
        return [_event_from_row(row) for row in rows]

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _get_required(connection: sqlite3.Connection, application_id: int) -> Application:
        row = connection.execute(
            "SELECT * FROM applications WHERE id = ?",
            (application_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"application {application_id} does not exist")
        return _application_from_row(row)

    @staticmethod
    def _append_event(
        connection: sqlite3.Connection,
        *,
        application_id: int,
        event_type: str,
        from_stage: Stage | None,
        to_stage: Stage | None,
        details: dict[str, str],
        happened_at: datetime,
    ) -> None:
        connection.execute(
            """
            INSERT INTO application_events (
                application_id, event_type, from_stage, to_stage, details, happened_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                application_id,
                event_type,
                from_stage.value if from_stage else None,
                to_stage.value if to_stage else None,
                json.dumps(details, sort_keys=True),
                happened_at.isoformat(),
            ),
        )


def _application_from_row(row: sqlite3.Row) -> Application:
    return Application(
        id=int(row["id"]),
        company=str(row["company"]),
        role=str(row["role"]),
        source=str(row["source"]) if row["source"] is not None else None,
        stage=Stage(str(row["stage"])),
        priority=int(row["priority"]),
        applied_on=_date_from_storage(row["applied_on"]),
        next_action=str(row["next_action"]) if row["next_action"] is not None else None,
        next_action_due=_date_from_storage(row["next_action_due"]),
        notes=str(row["notes"]),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
        version=int(row["version"]),
    )


def _event_from_row(row: sqlite3.Row) -> ApplicationEvent:
    parsed_details = json.loads(str(row["details"]))
    if not isinstance(parsed_details, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in parsed_details.items()
    ):
        raise ValueError("application event details are malformed")
    return ApplicationEvent(
        id=int(row["id"]),
        application_id=int(row["application_id"]),
        event_type=str(row["event_type"]),
        from_stage=Stage(str(row["from_stage"])) if row["from_stage"] is not None else None,
        to_stage=Stage(str(row["to_stage"])) if row["to_stage"] is not None else None,
        details=parsed_details,
        happened_at=datetime.fromisoformat(str(row["happened_at"])),
    )


def _date_to_storage(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _date_from_storage(value: object) -> date | None:
    return date.fromisoformat(str(value)) if value is not None else None


def _utc_now() -> datetime:
    return datetime.now(UTC)
