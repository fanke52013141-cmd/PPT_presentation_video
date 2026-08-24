from pathlib import Path
import tempfile

import pytest
from sqlalchemy import create_engine

from database_migrations import MIGRATIONS_DIR, MigrationError, run_migrations


def sqlite_engine(database_path: Path):
    return create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
    )


def table_names(engine) -> set[str]:
    with engine.connect() as connection:
        rows = connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    return {str(row[0]) for row in rows}


def test_numbered_migrations_apply_once_and_store_checksums() -> None:
    with tempfile.TemporaryDirectory() as value:
        engine = sqlite_engine(Path(value) / "fresh.db")

        assert run_migrations(engine) == [1, 2, 3, 4]
        assert run_migrations(engine) == []
        assert {"projects", "settings", "artifact_records", "local_jobs"}.issubset(
            table_names(engine)
        )

        with engine.connect() as connection:
            rows = connection.exec_driver_sql(
                "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
            ).fetchall()
            project_columns = {
                row[1]
                for row in connection.exec_driver_sql("PRAGMA table_info(projects)").fetchall()
            }
        assert [row[0] for row in rows] == [1, 2, 3, 4]
        assert [row[1] for row in rows] == [
            "core_schema",
            "project_ai_mode",
            "artifacts_and_local_jobs",
            "courses_and_chapters",
        ]
        assert all(len(row[2]) == 64 for row in rows)
        assert "ai_mode" in project_columns
        engine.dispose()


def test_legacy_marker_database_is_adopted_without_losing_data() -> None:
    with tempfile.TemporaryDirectory() as value:
        database_path = Path(value) / "legacy.db"
        engine = sqlite_engine(database_path)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                CREATE TABLE projects (
                    id VARCHAR PRIMARY KEY,
                    name VARCHAR NOT NULL,
                    description VARCHAR,
                    current_step INTEGER,
                    status VARCHAR,
                    step_status TEXT,
                    created_at DATETIME,
                    updated_at DATETIME,
                    run_dir VARCHAR NOT NULL
                )
                """
            )
            connection.exec_driver_sql(
                "CREATE TABLE settings (key VARCHAR PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE artifact_records (
                    id VARCHAR PRIMARY KEY,
                    project_id VARCHAR NOT NULL,
                    artifact_type VARCHAR NOT NULL,
                    filename VARCHAR NOT NULL,
                    relative_path VARCHAR NOT NULL,
                    mime_type VARCHAR NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    source_fingerprint TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at DATETIME NOT NULL
                )
                """
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE local_jobs (
                    id VARCHAR PRIMARY KEY,
                    project_id VARCHAR NOT NULL,
                    job_type VARCHAR NOT NULL,
                    status VARCHAR NOT NULL,
                    progress INTEGER NOT NULL,
                    stage VARCHAR NOT NULL,
                    error TEXT,
                    result_artifact_id VARCHAR,
                    payload_json TEXT NOT NULL,
                    created_at DATETIME NOT NULL,
                    started_at DATETIME,
                    finished_at DATETIME,
                    updated_at DATETIME NOT NULL
                )
                """
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE schema_migrations (
                    version VARCHAR PRIMARY KEY,
                    applied_at DATETIME NOT NULL
                )
                """
            )
            connection.exec_driver_sql(
                "INSERT INTO schema_migrations VALUES "
                "('0001_artifact_records_and_local_jobs', '2026-07-30 00:00:00')"
            )
            connection.exec_driver_sql(
                """
                INSERT INTO projects (
                    id, name, current_step, status, step_status, run_dir
                ) VALUES ('kept', '保留项目', 3, 'active', '{}', 'runs/kept')
                """
            )

        assert run_migrations(engine) == [1, 2, 3, 4]
        with engine.connect() as connection:
            project = connection.exec_driver_sql(
                "SELECT id, name, ai_mode FROM projects WHERE id = 'kept'"
            ).one()
            rows = connection.exec_driver_sql(
                "SELECT version, name FROM schema_migrations ORDER BY version"
            ).fetchall()
        assert tuple(project) == ("kept", "保留项目", "auto")
        assert [tuple(row) for row in rows] == [
            (1, "core_schema"),
            (2, "project_ai_mode"),
            (3, "artifacts_and_local_jobs"),
            (4, "courses_and_chapters"),
        ]
        engine.dispose()


def test_checksum_mismatch_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as value:
        root = Path(value)
        migrations = root / "migrations"
        migrations.mkdir()
        migration = migrations / "0001_example.sql"
        migration.write_text("CREATE TABLE example (id INTEGER PRIMARY KEY);\n", encoding="utf-8")
        engine = sqlite_engine(root / "checksum.db")

        assert run_migrations(engine, migrations) == [1]
        migration.write_text(
            "CREATE TABLE example (id INTEGER PRIMARY KEY, name TEXT);\n",
            encoding="utf-8",
        )
        with pytest.raises(MigrationError, match="checksum"):
            run_migrations(engine, migrations)
        engine.dispose()


def test_failed_migration_rolls_back_schema_and_ledger() -> None:
    with tempfile.TemporaryDirectory() as value:
        root = Path(value)
        migrations = root / "migrations"
        migrations.mkdir()
        (migrations / "0001_broken.sql").write_text(
            "CREATE TABLE should_rollback (id INTEGER PRIMARY KEY);\n"
            "INSERT INTO missing_table (id) VALUES (1);\n",
            encoding="utf-8",
        )
        engine = sqlite_engine(root / "rollback.db")

        with pytest.raises(MigrationError, match="failed to apply migration"):
            run_migrations(engine, migrations)

        assert "should_rollback" not in table_names(engine)
        with engine.connect() as connection:
            count = connection.exec_driver_sql(
                "SELECT COUNT(*) FROM schema_migrations"
            ).scalar_one()
        assert count == 0
        engine.dispose()


def test_production_migration_files_are_consecutive() -> None:
    with tempfile.TemporaryDirectory() as value:
        engine = sqlite_engine(Path(value) / "production-shape.db")
        assert run_migrations(engine, MIGRATIONS_DIR) == [1, 2, 3, 4]
        engine.dispose()
