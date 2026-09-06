from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable

from app.services.analysis_context_migration import (
    _ensure_dataset_scoped_analysis_snapshots,
    _ensure_nullable_imputation_structure,
    _migration_007_analysis_context_versions,
)


class DatabaseMigrationError(RuntimeError):
    pass


class DatabaseIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]


INITIAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dataset_versions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    original_name TEXT NOT NULL,
    file_format TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    manifest_path TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    column_count INTEGER NOT NULL,
    current_dictionary_version INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS dictionary_versions (
    dataset_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    path TEXT NOT NULL,
    confirmed_count INTEGER NOT NULL,
    PRIMARY KEY (dataset_id, version),
    FOREIGN KEY (dataset_id) REFERENCES dataset_versions(id)
);

CREATE TABLE IF NOT EXISTS measurement_versions (
    dataset_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    definition_path TEXT NOT NULL,
    derived_path TEXT NOT NULL,
    construct_count INTEGER NOT NULL,
    PRIMARY KEY (dataset_id, version),
    FOREIGN KEY (dataset_id) REFERENCES dataset_versions(id)
);

CREATE TABLE IF NOT EXISTS model_drafts (
    model_id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    path TEXT NOT NULL,
    model_hash TEXT NOT NULL,
    FOREIGN KEY (dataset_id) REFERENCES dataset_versions(id)
);

CREATE TABLE IF NOT EXISTS model_versions (
    model_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    dataset_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    path TEXT NOT NULL,
    model_hash TEXT NOT NULL,
    override_reason TEXT,
    PRIMARY KEY (model_id, version),
    FOREIGN KEY (dataset_id) REFERENCES dataset_versions(id)
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    model_version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    result_path TEXT NOT NULL,
    FOREIGN KEY (dataset_id) REFERENCES dataset_versions(id)
);

CREATE TABLE IF NOT EXISTS analysis_jobs (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    model_version INTEGER NOT NULL,
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    progress REAL NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    state_path TEXT NOT NULL,
    FOREIGN KEY (dataset_id) REFERENCES dataset_versions(id)
);
"""


def _migration_001_initial_schema(connection: sqlite3.Connection) -> None:
    for statement in INITIAL_SCHEMA.split(";"):
        if statement.strip():
            connection.execute(statement)


def _column_names(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _migration_002_job_lifecycle_metadata(connection: sqlite3.Connection) -> None:
    columns = _column_names(connection, "analysis_jobs")
    if "job_kind" not in columns:
        connection.execute(
            "ALTER TABLE analysis_jobs ADD COLUMN job_kind TEXT NOT NULL DEFAULT 'model'"
        )
    if "cancel_requested" not in columns:
        connection.execute(
            "ALTER TABLE analysis_jobs ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0"
        )
    if "result_path" not in columns:
        connection.execute("ALTER TABLE analysis_jobs ADD COLUMN result_path TEXT")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_analysis_jobs_status_created "
        "ON analysis_jobs(status, created_at)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_analysis_runs_created ON analysis_runs(created_at)"
    )


def _migration_003_advanced_analysis_jobs(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS advanced_analysis_jobs (
            id TEXT PRIMARY KEY,
            analysis_id TEXT NOT NULL,
            family TEXT NOT NULL,
            spec_hash TEXT NOT NULL,
            dataset_version_id TEXT,
            status TEXT NOT NULL,
            stage TEXT NOT NULL,
            progress REAL NOT NULL,
            cancel_requested INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            state_path TEXT NOT NULL,
            result_path TEXT,
            FOREIGN KEY (dataset_version_id) REFERENCES dataset_versions(id)
        );
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_advanced_jobs_status_created "
        "ON advanced_analysis_jobs(status, created_at)"
    )


def _migration_004_protocols_and_programs(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS research_programs (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            theoretical_question TEXT NOT NULL,
            target_journal TEXT,
            owner TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS study_protocols (
            study_id TEXT NOT NULL,
            version_id TEXT NOT NULL,
            program_id TEXT NOT NULL,
            title TEXT NOT NULL,
            design_type TEXT NOT NULL,
            is_frozen INTEGER NOT NULL DEFAULT 0,
            frozen_hash TEXT,
            path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (study_id, version_id),
            FOREIGN KEY (program_id) REFERENCES research_programs(id)
        );
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS hypotheses (
            id TEXT PRIMARY KEY,
            program_id TEXT NOT NULL,
            study_id TEXT NOT NULL,
            text TEXT NOT NULL,
            directionality TEXT NOT NULL,
            analysis_role TEXT NOT NULL,
            is_preregistered INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'untested',
            created_at TEXT NOT NULL,
            FOREIGN KEY (program_id) REFERENCES research_programs(id)
        );
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS study_deviations (
            id TEXT PRIMARY KEY,
            study_id TEXT NOT NULL,
            version_id TEXT NOT NULL,
            analysis_id TEXT NOT NULL,
            deviation_type TEXT NOT NULL,
            field_path TEXT NOT NULL,
            expected_value TEXT,
            actual_value TEXT,
            reason TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_protocols_program ON study_protocols(program_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_hypotheses_study ON hypotheses(program_id, study_id)"
    )


def _migration_005_r1_quality_and_protocol_identity(connection: sqlite3.Connection) -> None:
    # Include the program in protocol identity before adding quality and
    # sample-lineage tables.
    connection.execute(
        """
        CREATE TABLE study_protocols_v2 (
            study_id TEXT NOT NULL,
            version_id TEXT NOT NULL,
            program_id TEXT NOT NULL,
            title TEXT NOT NULL,
            design_type TEXT NOT NULL,
            is_frozen INTEGER NOT NULL DEFAULT 0,
            frozen_hash TEXT,
            path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (program_id, study_id, version_id),
            FOREIGN KEY (program_id) REFERENCES research_programs(id)
        )
        """
    )
    connection.execute(
        """
        INSERT INTO study_protocols_v2
        SELECT study_id, version_id, program_id, title, design_type,
               is_frozen, frozen_hash, path, created_at, updated_at
        FROM study_protocols
        """
    )
    connection.execute("DROP TABLE study_protocols")
    connection.execute("ALTER TABLE study_protocols_v2 RENAME TO study_protocols")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_protocols_program ON study_protocols(program_id)"
    )
    if "program_id" not in _column_names(connection, "study_deviations"):
        connection.execute(
            "ALTER TABLE study_deviations ADD COLUMN program_id TEXT NOT NULL DEFAULT ''"
        )
    hypothesis_columns = _column_names(connection, "hypotheses")
    if "construct_keys" not in hypothesis_columns:
        connection.execute(
            "ALTER TABLE hypotheses ADD COLUMN construct_keys TEXT NOT NULL DEFAULT '[]'"
        )
    if "estimand_ids" not in hypothesis_columns:
        connection.execute(
            "ALTER TABLE hypotheses ADD COLUMN estimand_ids TEXT NOT NULL DEFAULT '[]'"
        )
    if "evidence_ids" not in hypothesis_columns:
        connection.execute(
            "ALTER TABLE hypotheses ADD COLUMN evidence_ids TEXT NOT NULL DEFAULT '[]'"
        )
    if "counterevidence" not in hypothesis_columns:
        connection.execute("ALTER TABLE hypotheses ADD COLUMN counterevidence TEXT")

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS data_quality_runs (
            id TEXT PRIMARY KEY,
            dataset_version_id TEXT NOT NULL,
            dataset_sha256 TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            case_metrics_path TEXT NOT NULL,
            case_metrics_hash TEXT NOT NULL,
            summary_path TEXT NOT NULL,
            FOREIGN KEY (dataset_version_id) REFERENCES dataset_versions(id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS analysis_sample_versions (
            id TEXT PRIMARY KEY,
            dataset_version_id TEXT NOT NULL,
            dataset_sha256 TEXT NOT NULL,
            quality_run_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            label TEXT NOT NULL,
            combine_operator TEXT NOT NULL,
            rules_hash TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            included_count INTEGER NOT NULL,
            excluded_count INTEGER NOT NULL,
            boundary_count INTEGER NOT NULL,
            sample_hash TEXT NOT NULL,
            case_records_path TEXT NOT NULL,
            case_records_hash TEXT NOT NULL,
            summary_path TEXT NOT NULL,
            FOREIGN KEY (dataset_version_id) REFERENCES dataset_versions(id),
            FOREIGN KEY (quality_run_id) REFERENCES data_quality_runs(id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS result_invalidations (
            id TEXT PRIMARY KEY,
            dataset_version_id TEXT NOT NULL,
            sample_version_id TEXT NOT NULL,
            sample_hash TEXT NOT NULL,
            analysis_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (dataset_version_id) REFERENCES dataset_versions(id)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_quality_runs_dataset ON data_quality_runs(dataset_version_id, created_at)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_samples_dataset ON analysis_sample_versions(dataset_version_id, created_at)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_invalidations_analysis ON result_invalidations(analysis_id, created_at)"
    )


def _migration_006_study_context_and_dataset_structure(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS study_contexts (
            project_id TEXT PRIMARY KEY,
            schema_version TEXT NOT NULL,
            time_structure TEXT NOT NULL,
            dependence_structure TEXT NOT NULL,
            design TEXT NOT NULL,
            revision INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS dataset_structures (
            dataset_version_id TEXT PRIMARY KEY,
            context_json TEXT NOT NULL,
            subject_id TEXT,
            cluster_id TEXT,
            time_id TEXT,
            revision INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (dataset_version_id) REFERENCES dataset_versions(id)
        )
        """
    )


def _migration_008_nullable_imputation_structure(connection: sqlite3.Connection) -> None:
    """Allow independent cross-sectional plans to omit a structure version."""

    _ensure_nullable_imputation_structure(connection)


def _migration_009_dataset_scoped_analysis_snapshots(connection: sqlite3.Connection) -> None:
    """Scope analysis snapshots to their dataset version."""

    _ensure_dataset_scoped_analysis_snapshots(connection)


MIGRATIONS = (
    Migration(1, "initial_schema", _migration_001_initial_schema),
    Migration(2, "job_lifecycle_metadata", _migration_002_job_lifecycle_metadata),
    Migration(3, "advanced_analysis_jobs", _migration_003_advanced_analysis_jobs),
    Migration(4, "protocols_and_programs", _migration_004_protocols_and_programs),
    Migration(
        5, "r1_quality_and_protocol_identity", _migration_005_r1_quality_and_protocol_identity
    ),
    Migration(6, "study_context_and_dataset_structure", _migration_006_study_context_and_dataset_structure),
    Migration(7, "analysis_context_versions", _migration_007_analysis_context_versions),
    Migration(8, "nullable_imputation_structure", _migration_008_nullable_imputation_structure),
    Migration(9, "dataset_scoped_analysis_snapshots", _migration_009_dataset_scoped_analysis_snapshots),
)
CURRENT_DATABASE_VERSION = MIGRATIONS[-1].version


def apply_migrations(
    connection: sqlite3.Connection,
    migrations: Iterable[Migration] = MIGRATIONS,
) -> int:
    current = int(connection.execute("PRAGMA user_version").fetchone()[0])
    migration_list = tuple(migrations)
    latest = max((migration.version for migration in migration_list), default=current)
    if current > latest:
        raise DatabaseMigrationError(f"数据库版本 {current} 高于当前程序支持的版本 {latest}")
    for migration in migration_list:
        if migration.version <= current:
            continue
        if migration.version != current + 1:
            raise DatabaseMigrationError(
                f"数据库迁移链不连续：当前 {current}，下一项 {migration.version}"
            )
        try:
            connection.execute("BEGIN IMMEDIATE")
            migration.apply(connection)
            connection.execute(
                "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                (
                    migration.version,
                    migration.name,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            connection.execute(f"PRAGMA user_version = {migration.version}")
            connection.commit()
        except Exception as error:
            connection.rollback()
            raise DatabaseMigrationError(
                f"数据库迁移 {migration.version} ({migration.name}) 失败: {error}"
            ) from error
        current = migration.version
    return current


def verify_database_integrity(connection: sqlite3.Connection) -> None:
    quick_check = [str(row[0]) for row in connection.execute("PRAGMA quick_check")]
    if quick_check != ["ok"]:
        raise DatabaseIntegrityError("SQLite quick_check 失败: " + "; ".join(quick_check))
    violations = list(connection.execute("PRAGMA foreign_key_check"))
    if violations:
        rendered = "; ".join(
            f"table={row[0]}, rowid={row[1]}, parent={row[2]}" for row in violations[:20]
        )
        raise DatabaseIntegrityError("SQLite 外键完整性检查失败: " + rendered)


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA journal_mode=WAL")
    apply_migrations(connection)
    verify_database_integrity(connection)
