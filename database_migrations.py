"""Numbered, transactional SQLite schema migrations.

Production startup must use this module instead of ``Base.metadata.create_all``.
Each ``NNNN_name.sql`` file is checksummed, applied once, and recorded in
``schema_migrations`` in the same transaction as its schema changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import sqlite3
import threading
from typing import Iterable

from sqlalchemy.engine import Connection, Engine


MIGRATION_FILE_PATTERN = re.compile(r"^(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.sql$")
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_MIGRATION_LOCK = threading.Lock()


class MigrationError(RuntimeError):
    """Raised when migration discovery, integrity, or execution fails."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path
    sql: str
    checksum: str


def discover_migrations(migrations_dir: str | Path = MIGRATIONS_DIR) -> list[Migration]:
    root = Path(migrations_dir)
    if not root.is_dir():
        raise MigrationError(f"migration directory does not exist: {root}")

    migrations: list[Migration] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if path.suffix.lower() != ".sql":
            continue
        match = MIGRATION_FILE_PATTERN.fullmatch(path.name)
        if not match:
            raise MigrationError(
                f"invalid migration filename {path.name!r}; expected NNNN_lowercase_name.sql"
            )
        raw = path.read_bytes()
        sql = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
        migrations.append(
            Migration(
                version=int(match.group("version")),
                name=match.group("name"),
                path=path,
                sql=sql,
                # Git may check out the same migration with CRLF or LF. The
                # logical SQL checksum must remain stable across platforms.
                checksum=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
            )
        )

    if not migrations:
        raise MigrationError(f"no numbered SQL migrations found in {root}")

    versions = [migration.version for migration in migrations]
    expected = list(range(1, len(migrations) + 1))
    if versions != expected:
        raise MigrationError(
            f"migration versions must be unique and consecutive from 0001; "
            f"found {versions}, expected {expected}"
        )
    return migrations


def _table_names(connection: Connection) -> set[str]:
    rows = connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _column_names(connection: Connection, table_name: str) -> set[str]:
    if table_name not in _table_names(connection):
        return set()
    escaped = table_name.replace('"', '""')
    rows = connection.exec_driver_sql(f'PRAGMA table_info("{escaped}")').fetchall()
    return {str(row[1]) for row in rows}


def _create_metadata_table(connection: Connection) -> None:
    connection.exec_driver_sql(
        """
        CREATE TABLE schema_migrations (
            version INTEGER NOT NULL PRIMARY KEY,
            name VARCHAR NOT NULL,
            checksum VARCHAR(64) NOT NULL,
            applied_at DATETIME NOT NULL
        )
        """
    )


def _ensure_metadata_table(engine: Engine) -> None:
    """Create the ledger, replacing the old two-column marker table if needed."""
    with engine.connect() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            tables = _table_names(connection)
            if "schema_migrations" not in tables:
                _create_metadata_table(connection)
            else:
                columns = _column_names(connection, "schema_migrations")
                required = {"version", "name", "checksum", "applied_at"}
                if not required.issubset(columns):
                    legacy_versions = {
                        str(row[0])
                        for row in connection.exec_driver_sql(
                            "SELECT version FROM schema_migrations"
                        ).fetchall()
                    }
                    supported_legacy_markers = {
                        "0001_artifact_records_and_local_jobs",
                    }
                    unknown_markers = sorted(legacy_versions - supported_legacy_markers)
                    if unknown_markers:
                        raise MigrationError(
                            "legacy migration ledger contains unknown markers: "
                            f"{unknown_markers}"
                        )
                    connection.exec_driver_sql(
                        "ALTER TABLE schema_migrations RENAME TO schema_migrations_legacy"
                    )
                    _create_metadata_table(connection)
                    connection.exec_driver_sql("DROP TABLE schema_migrations_legacy")
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def _split_sql_statements(sql: str) -> Iterable[str]:
    """Split SQLite statements without breaking quoted semicolons."""
    buffer = ""
    for character in sql:
        buffer += character
        if character == ";" and sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                yield statement
            buffer = ""
    if buffer.strip():
        raise MigrationError("migration SQL ends with an incomplete statement")


def _has_columns(
    connection: Connection,
    table_name: str,
    required_columns: set[str],
) -> bool:
    return required_columns.issubset(_column_names(connection, table_name))


def _known_migration_already_present(connection: Connection, migration: Migration) -> bool:
    """Adopt schemas created by releases that predated the real ledger."""
    key = (migration.version, migration.name)
    if key == (1, "core_schema"):
        return _has_columns(
            connection,
            "projects",
            {
                "id",
                "name",
                "description",
                "current_step",
                "status",
                "step_status",
                "created_at",
                "updated_at",
                "run_dir",
            },
        ) and _has_columns(connection, "settings", {"key", "value"})
    if key == (2, "project_ai_mode"):
        return _has_columns(connection, "projects", {"ai_mode"})
    if key == (3, "artifacts_and_local_jobs"):
        return _has_columns(
            connection,
            "artifact_records",
            {
                "id",
                "project_id",
                "artifact_type",
                "filename",
                "relative_path",
                "mime_type",
                "size_bytes",
                "source_fingerprint",
                "metadata_json",
                "created_at",
            },
        ) and _has_columns(
            connection,
            "local_jobs",
            {
                "id",
                "project_id",
                "job_type",
                "status",
                "progress",
                "stage",
                "error",
                "result_artifact_id",
                "payload_json",
                "created_at",
                "started_at",
                "finished_at",
                "updated_at",
            },
        )
    if key == (4, "courses_and_chapters"):
        return _has_columns(connection, "courses", {"id", "name", "cover_color", "sort_order"}) \
            and _has_columns(connection, "chapters", {"id", "course_id", "name", "sort_order"}) \
            and _has_columns(connection, "projects", {"course_id", "chapter_id", "sort_order"})
    return False


def _applied_rows(connection: Connection) -> dict[int, tuple[str, str]]:
    rows = connection.exec_driver_sql(
        "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
    ).fetchall()
    return {int(row[0]): (str(row[1]), str(row[2])) for row in rows}


def run_migrations(
    engine: Engine,
    migrations_dir: str | Path = MIGRATIONS_DIR,
) -> list[int]:
    """Apply all pending migrations and return versions changed in this run."""
    migrations = discover_migrations(migrations_dir)
    known_versions = {migration.version for migration in migrations}

    with _MIGRATION_LOCK:
        _ensure_metadata_table(engine)
        with engine.connect() as connection:
            applied = _applied_rows(connection)
        unknown = sorted(set(applied) - known_versions)
        if unknown:
            raise MigrationError(
                f"database contains migration versions unavailable in this build: {unknown}"
            )

        changed: list[int] = []
        for migration in migrations:
            with engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    current = _applied_rows(connection).get(migration.version)
                    if current is not None:
                        current_name, current_checksum = current
                        if current_name != migration.name:
                            raise MigrationError(
                                f"migration {migration.version:04d} name changed from "
                                f"{current_name!r} to {migration.name!r}"
                            )
                        if current_checksum != migration.checksum:
                            raise MigrationError(
                                f"migration {migration.version:04d}_{migration.name} "
                                "checksum does not match the applied migration"
                            )
                        connection.commit()
                        continue

                    if not _known_migration_already_present(connection, migration):
                        for statement in _split_sql_statements(migration.sql):
                            connection.exec_driver_sql(statement)

                    connection.exec_driver_sql(
                        """
                        INSERT INTO schema_migrations (version, name, checksum, applied_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            migration.version,
                            migration.name,
                            migration.checksum,
                            datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        ),
                    )
                    connection.commit()
                    changed.append(migration.version)
                except Exception as exc:
                    connection.rollback()
                    if isinstance(exc, MigrationError):
                        raise
                    raise MigrationError(
                        f"failed to apply migration "
                        f"{migration.version:04d}_{migration.name}: {exc}"
                    ) from exc
        return changed
