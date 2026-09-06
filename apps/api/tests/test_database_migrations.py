from __future__ import annotations

import sqlite3
from dataclasses import replace

import pytest

from app.services.analysis_context_migration import (
    _ensure_dataset_scoped_analysis_snapshots,
    _ensure_nullable_imputation_structure,
)
from app.services.database_migrations import (
    CURRENT_DATABASE_VERSION,
    MIGRATIONS,
    DatabaseMigrationError,
    Migration,
    apply_migrations,
)
from app.services.dataset_repository import DatasetRepository
from app.settings import get_settings


def test_fresh_database_has_versioned_schema_and_enforced_foreign_keys(
    tmp_path,
) -> None:
    settings = replace(get_settings(), state_root=tmp_path / "workspace")
    repository = DatasetRepository(settings)

    with repository._connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == (CURRENT_DATABASE_VERSION)
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        applied = connection.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert [(row["version"], row["name"]) for row in applied] == [
            (migration.version, migration.name) for migration in MIGRATIONS
        ]
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO dictionary_versions "
                "(dataset_id, version, created_at, path, confirmed_count) "
                "VALUES ('missing', 1, '2026-07-14', 'missing.json', 0)"
            )


def test_version_one_database_upgrades_in_place_and_is_idempotent(
    tmp_path,
) -> None:
    settings = replace(get_settings(), state_root=tmp_path / "workspace")
    database_path = settings.state_root / "metadata.sqlite3"
    database_path.parent.mkdir(parents=True)
    with sqlite3.connect(database_path) as connection:
        apply_migrations(connection, MIGRATIONS[:1])
        connection.execute(
            "INSERT INTO dataset_versions "
            "(id, project_id, created_at, original_name, file_format, sha256, "
            "manifest_path, row_count, column_count) "
            "VALUES ('seed', 'default', '2026-07-14', 'seed.csv', 'csv', "
            "'abc', 'seed.json', 1, 1)"
        )

    DatasetRepository(settings)
    DatasetRepository(settings)
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == (CURRENT_DATABASE_VERSION)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(analysis_jobs)")}
        assert {"job_kind", "cancel_requested", "result_path"} <= columns
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM dataset_versions WHERE id = 'seed'"
            ).fetchone()[0]
            == 1
        )
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == len(
            MIGRATIONS
        )


def test_future_database_version_is_rejected(tmp_path) -> None:
    settings = replace(get_settings(), state_root=tmp_path / "workspace")
    database_path = settings.state_root / "metadata.sqlite3"
    database_path.parent.mkdir(parents=True)
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA user_version = 999")
    with pytest.raises(DatabaseMigrationError, match="高于当前程序支持"):
        DatasetRepository(settings)


def test_failed_migration_rolls_back_schema_and_version(tmp_path) -> None:
    database_path = tmp_path / "rollback.sqlite3"
    with sqlite3.connect(database_path) as connection:
        apply_migrations(connection)

        def fail_after_ddl(target: sqlite3.Connection) -> None:
            target.execute("CREATE TABLE should_rollback(id INTEGER PRIMARY KEY)")
            raise RuntimeError("injected migration failure")

        failing = Migration(
            CURRENT_DATABASE_VERSION + 1,
            "injected_failure",
            fail_after_ddl,
        )
        with pytest.raises(DatabaseMigrationError, match="injected_failure"):
            apply_migrations(connection, (*MIGRATIONS, failing))
        assert connection.execute("PRAGMA user_version").fetchone()[0] == (CURRENT_DATABASE_VERSION)
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'should_rollback'"
        ).fetchone()
        assert table is None


def test_nullable_imputation_structure_rebuild_preserves_existing_artifacts() -> None:
    with sqlite3.connect(":memory:") as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            CREATE TABLE dataset_versions (id TEXT PRIMARY KEY);
            CREATE TABLE dataset_structure_versions (id TEXT PRIMARY KEY);
            CREATE TABLE advanced_analysis_jobs (id TEXT PRIMARY KEY);
            CREATE TABLE imputation_plan_versions (
                id TEXT PRIMARY KEY, dataset_version_id TEXT NOT NULL,
                structure_version_id TEXT NOT NULL, sample_identity TEXT NOT NULL,
                sample_hash TEXT NOT NULL, measurement_version_id TEXT,
                context_hash TEXT NOT NULL, substantive_model_hash TEXT NOT NULL,
                plan_hash TEXT NOT NULL UNIQUE, payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(dataset_version_id) REFERENCES dataset_versions(id),
                FOREIGN KEY(structure_version_id) REFERENCES dataset_structure_versions(id)
            );
            CREATE TABLE imputation_dataset_versions (
                id TEXT PRIMARY KEY, plan_version_id TEXT NOT NULL, job_id TEXT NOT NULL,
                artifact_manifest_path TEXT NOT NULL, artifact_hash TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('ready','failed','superseded')),
                created_at TEXT NOT NULL,
                FOREIGN KEY(plan_version_id) REFERENCES imputation_plan_versions(id),
                FOREIGN KEY(job_id) REFERENCES advanced_analysis_jobs(id)
            );
            INSERT INTO dataset_versions VALUES ('dataset-1');
            INSERT INTO dataset_structure_versions VALUES ('structure-1');
            INSERT INTO advanced_analysis_jobs VALUES ('job-1');
            INSERT INTO imputation_plan_versions VALUES
                ('plan-1', 'dataset-1', 'structure-1', 'sample-1', 'aaaaaaaa', NULL,
                 'bbbbbbbb', 'cccccccc', 'dddddddd', '{}', '2026-08-02');
            INSERT INTO imputation_dataset_versions VALUES
                ('artifact-1', 'plan-1', 'job-1', 'artifact.json', 'eeeeeeee', 'ready', '2026-08-02');
            """
        )

        _ensure_nullable_imputation_structure(connection)

        structure_column = next(
            row for row in connection.execute("PRAGMA table_info(imputation_plan_versions)")
            if row[1] == "structure_version_id"
        )
        assert structure_column[3] == 0
        assert connection.execute(
            "SELECT structure_version_id FROM imputation_plan_versions WHERE id = 'plan-1'"
        ).fetchone()[0] == "structure-1"
        assert connection.execute(
            "SELECT plan_version_id FROM imputation_dataset_versions WHERE id = 'artifact-1'"
        ).fetchone()[0] == "plan-1"

        connection.execute(
            "INSERT INTO imputation_plan_versions "
            "(id, dataset_version_id, structure_version_id, sample_identity, sample_hash, "
            "measurement_version_id, context_hash, substantive_model_hash, plan_hash, payload_json, created_at) "
            "VALUES ('plan-2', 'dataset-1', NULL, 'sample-2', 'ffffffff', NULL, "
            "'gggggggg', 'hhhhhhhh', 'iiiiiiii', '{}', '2026-08-02')"
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_analysis_snapshots_become_dataset_scoped_without_losing_drafts() -> None:
    with sqlite3.connect(":memory:") as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            CREATE TABLE dataset_versions (id TEXT PRIMARY KEY);
            CREATE TABLE analysis_context_snapshots (
                id TEXT PRIMARY KEY, dataset_version_id TEXT NOT NULL,
                context_hash TEXT NOT NULL UNIQUE, payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(dataset_version_id) REFERENCES dataset_versions(id)
            );
            CREATE TABLE analysis_drafts (
                id TEXT PRIMARY KEY, dataset_version_id TEXT NOT NULL, revision INTEGER NOT NULL,
                family TEXT NOT NULL, slice_id TEXT NOT NULL, context_snapshot_id TEXT NOT NULL,
                context_hash TEXT NOT NULL, spec_json TEXT NOT NULL,
                role_overrides_json TEXT NOT NULL DEFAULT '{}',
                validity TEXT NOT NULL CHECK(validity IN ('ready','incomplete','stale','superseded')),
                invalidation_reasons_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(dataset_version_id) REFERENCES dataset_versions(id),
                FOREIGN KEY(context_snapshot_id) REFERENCES analysis_context_snapshots(id)
            );
            INSERT INTO dataset_versions VALUES ('dataset-1');
            INSERT INTO dataset_versions VALUES ('dataset-2');
            INSERT INTO analysis_context_snapshots VALUES
                ('snapshot-1', 'dataset-1', 'same-context', '{}', '2026-08-02');
            INSERT INTO analysis_drafts VALUES
                ('draft-1', 'dataset-1', 1, 'questionnaire', 'reliability', 'snapshot-1',
                 'same-context', '{}', '{}', 'ready', '[]', '2026-08-02', '2026-08-02');
            """
        )

        _ensure_dataset_scoped_analysis_snapshots(connection)

        connection.execute(
            "INSERT INTO analysis_context_snapshots "
            "(id, dataset_version_id, context_hash, payload_json, created_at) "
            "VALUES ('snapshot-2', 'dataset-2', 'same-context', '{}', '2026-08-02')"
        )
        assert connection.execute(
            "SELECT context_snapshot_id FROM analysis_drafts WHERE id = 'draft-1'"
        ).fetchone()[0] == "snapshot-1"
        assert connection.execute(
            "SELECT COUNT(*) FROM analysis_context_snapshots WHERE context_hash = 'same-context'"
        ).fetchone()[0] == 2
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migration_repairs_are_safe_for_missing_source_child_tables() -> None:
    with sqlite3.connect(":memory:") as connection:
        _ensure_dataset_scoped_analysis_snapshots(connection)

        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            CREATE TABLE dataset_versions (id TEXT PRIMARY KEY);
            CREATE TABLE dataset_structure_versions (id TEXT PRIMARY KEY);
            CREATE TABLE imputation_plan_versions (
                id TEXT PRIMARY KEY, dataset_version_id TEXT NOT NULL,
                structure_version_id TEXT NOT NULL, sample_identity TEXT NOT NULL,
                sample_hash TEXT NOT NULL, measurement_version_id TEXT,
                context_hash TEXT NOT NULL, substantive_model_hash TEXT NOT NULL,
                plan_hash TEXT NOT NULL UNIQUE, payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(dataset_version_id) REFERENCES dataset_versions(id),
                FOREIGN KEY(structure_version_id) REFERENCES dataset_structure_versions(id)
            );
            INSERT INTO dataset_versions VALUES ('dataset-1');
            INSERT INTO dataset_structure_versions VALUES ('structure-1');
            INSERT INTO imputation_plan_versions VALUES
                ('plan-1', 'dataset-1', 'structure-1', 'sample-1', 'aaaaaaaa', NULL,
                 'bbbbbbbb', 'cccccccc', 'dddddddd', '{}', '2026-08-02');
            """
        )

        _ensure_nullable_imputation_structure(connection)

        structure_column = next(
            row for row in connection.execute("PRAGMA table_info(imputation_plan_versions)")
            if row[1] == "structure_version_id"
        )
        assert structure_column[3] == 0


def test_analysis_snapshot_repair_handles_extra_indexes_without_draft_table() -> None:
    with sqlite3.connect(":memory:") as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            CREATE TABLE dataset_versions (id TEXT PRIMARY KEY);
            CREATE TABLE analysis_context_snapshots (
                id TEXT PRIMARY KEY, dataset_version_id TEXT NOT NULL,
                context_hash TEXT NOT NULL UNIQUE, payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(dataset_version_id) REFERENCES dataset_versions(id)
            );
            CREATE INDEX snapshot_dataset_lookup ON analysis_context_snapshots(dataset_version_id);
            INSERT INTO dataset_versions VALUES ('dataset-1');
            INSERT INTO dataset_versions VALUES ('dataset-2');
            INSERT INTO analysis_context_snapshots VALUES
                ('snapshot-1', 'dataset-1', 'same-context', '{}', '2026-08-02');
            """
        )

        _ensure_dataset_scoped_analysis_snapshots(connection)

        connection.execute(
            "INSERT INTO analysis_context_snapshots "
            "(id, dataset_version_id, context_hash, payload_json, created_at) "
            "VALUES ('snapshot-2', 'dataset-2', 'same-context', '{}', '2026-08-02')"
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM analysis_context_snapshots"
        ).fetchone()[0] == 2
