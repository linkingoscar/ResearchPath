from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd

from app.services.canonical_identity import canonical_sha256
from app.services.study_structure_profile import profile_structure


def _column_names(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _ensure_nullable_imputation_structure(connection: sqlite3.Connection) -> None:
    """Allow independent cross-sectional plans to omit structure roles.

    SQLite cannot alter the constraint in place, so only tables that still
    require ``structure_version_id`` are rebuilt.
    """
    columns = connection.execute("PRAGMA table_info(imputation_plan_versions)").fetchall()
    structure_column = next((row for row in columns if row[1] == "structure_version_id"), None)
    if structure_column is None or not bool(structure_column[3]):
        return
    # SQLite propagates a parent-table rename into child foreign keys.  The
    # imputation artifact table therefore has to be rebuilt in the same
    # transaction as the parent table; toggling PRAGMA foreign_keys here is
    # ineffective because migrations run inside BEGIN IMMEDIATE.
    connection.execute("ALTER TABLE imputation_plan_versions RENAME TO imputation_plan_versions_previous")
    connection.execute(
        """
        CREATE TABLE imputation_plan_versions (
            id TEXT PRIMARY KEY, dataset_version_id TEXT NOT NULL, structure_version_id TEXT,
            sample_identity TEXT NOT NULL, sample_hash TEXT NOT NULL, measurement_version_id TEXT,
            context_hash TEXT NOT NULL, substantive_model_hash TEXT NOT NULL, plan_hash TEXT NOT NULL UNIQUE,
            payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
            FOREIGN KEY(dataset_version_id) REFERENCES dataset_versions(id),
            FOREIGN KEY(structure_version_id) REFERENCES dataset_structure_versions(id)
        )
        """
    )
    connection.execute(
        "INSERT INTO imputation_plan_versions "
        "(id, dataset_version_id, structure_version_id, sample_identity, sample_hash, "
        "measurement_version_id, context_hash, substantive_model_hash, plan_hash, payload_json, created_at) "
        "SELECT id, dataset_version_id, structure_version_id, sample_identity, sample_hash, "
        "measurement_version_id, context_hash, substantive_model_hash, plan_hash, payload_json, created_at "
        "FROM imputation_plan_versions_previous"
    )

    # This is the only child table that references imputation_plan_versions.
    # Recreate it with the parent identity so completed artifacts remain valid
    # while referential integrity stays enabled.
    child_columns = _column_names(connection, "imputation_dataset_versions")
    if child_columns:
        connection.execute("ALTER TABLE imputation_dataset_versions RENAME TO imputation_dataset_versions_previous")
        connection.execute(
            """
            CREATE TABLE imputation_dataset_versions_rebuild (
                id TEXT PRIMARY KEY, plan_version_id TEXT NOT NULL, job_id TEXT NOT NULL,
                artifact_manifest_path TEXT NOT NULL, artifact_hash TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('ready','failed','superseded')),
                created_at TEXT NOT NULL,
                FOREIGN KEY(plan_version_id) REFERENCES imputation_plan_versions(id),
                FOREIGN KEY(job_id) REFERENCES advanced_analysis_jobs(id)
            )
            """
        )
        connection.execute(
            "INSERT INTO imputation_dataset_versions_rebuild "
            "(id, plan_version_id, job_id, artifact_manifest_path, artifact_hash, status, created_at) "
            "SELECT id, plan_version_id, job_id, artifact_manifest_path, artifact_hash, status, created_at "
            "FROM imputation_dataset_versions_previous"
        )
        connection.execute("DROP TABLE imputation_dataset_versions_previous")
        connection.execute(
            "ALTER TABLE imputation_dataset_versions_rebuild RENAME TO imputation_dataset_versions"
        )

    connection.execute("DROP TABLE imputation_plan_versions_previous")


def _ensure_dataset_scoped_analysis_snapshots(connection: sqlite3.Connection) -> None:
    """Scope context snapshots to a dataset version.

    A context hash describes the study context, not the data artifact it is
    attached to.  The original schema made that hash globally unique, so a
    second dataset with the same study context caused ``INSERT OR IGNORE`` to
    discard its snapshot and left the subsequent draft pointing at a missing
    foreign key.  Rebuild the parent and its draft child with the correct
    composite uniqueness constraint while preserving existing rows.
    """

    if not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'analysis_context_snapshots'"
    ).fetchone():
        return
    unique_indexes = connection.execute(
        "PRAGMA index_list(analysis_context_snapshots)"
    ).fetchall()
    has_global_context_unique = False
    for index in unique_indexes:
        if not bool(index[2]):
            continue
        index_columns = [
            str(row[2])
            for row in connection.execute(f"PRAGMA index_info({index[1]})").fetchall()
        ]
        if index_columns == ["context_hash"]:
            has_global_context_unique = True
            break
    if not has_global_context_unique:
        return

    connection.execute(
        "ALTER TABLE analysis_context_snapshots RENAME TO analysis_context_snapshots_previous"
    )
    connection.execute(
        """
        CREATE TABLE analysis_context_snapshots (
            id TEXT PRIMARY KEY, dataset_version_id TEXT NOT NULL,
            context_hash TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
            UNIQUE(dataset_version_id, context_hash),
            FOREIGN KEY(dataset_version_id) REFERENCES dataset_versions(id)
        )
        """
    )
    connection.execute(
        "INSERT INTO analysis_context_snapshots "
        "(id, dataset_version_id, context_hash, payload_json, created_at) "
        "SELECT id, dataset_version_id, context_hash, payload_json, created_at "
        "FROM analysis_context_snapshots_previous"
    )

    draft_columns = _column_names(connection, "analysis_drafts")
    if draft_columns:
        connection.execute("ALTER TABLE analysis_drafts RENAME TO analysis_drafts_previous")
        connection.execute(
            """
            CREATE TABLE analysis_drafts_rebuild (
                id TEXT PRIMARY KEY, dataset_version_id TEXT NOT NULL, revision INTEGER NOT NULL,
                family TEXT NOT NULL, slice_id TEXT NOT NULL, context_snapshot_id TEXT NOT NULL,
                context_hash TEXT NOT NULL, spec_json TEXT NOT NULL,
                role_overrides_json TEXT NOT NULL DEFAULT '{}',
                validity TEXT NOT NULL CHECK(validity IN ('ready','incomplete','stale','superseded')),
                invalidation_reasons_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(dataset_version_id) REFERENCES dataset_versions(id),
                FOREIGN KEY(context_snapshot_id) REFERENCES analysis_context_snapshots(id)
            )
            """
        )
        connection.execute(
            "INSERT INTO analysis_drafts_rebuild "
            "(id, dataset_version_id, revision, family, slice_id, context_snapshot_id, "
            "context_hash, spec_json, role_overrides_json, validity, "
            "invalidation_reasons_json, created_at, updated_at) "
            "SELECT id, dataset_version_id, revision, family, slice_id, context_snapshot_id, "
            "context_hash, spec_json, role_overrides_json, validity, "
            "invalidation_reasons_json, created_at, updated_at "
            "FROM analysis_drafts_previous"
        )
        connection.execute("DROP TABLE analysis_drafts_previous")
        connection.execute("ALTER TABLE analysis_drafts_rebuild RENAME TO analysis_drafts")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_analysis_drafts_dataset "
            "ON analysis_drafts(dataset_version_id, updated_at DESC)"
        )

    connection.execute("DROP TABLE analysis_context_snapshots_previous")


def _state_root(connection: sqlite3.Connection) -> Path | None:
    database_path = str(connection.execute("PRAGMA database_list").fetchone()[2])
    return Path(database_path).resolve().parent if database_path else None


def _source_frame(
    connection: sqlite3.Connection, dataset_id: str
) -> tuple[dict[str, object], pd.DataFrame]:
    state_root = _state_root(connection)
    if state_root is None:
        raise RuntimeError("无法从内存数据库解析源数据版本的规范化路径")
    row = connection.execute(
        "SELECT manifest_path FROM dataset_versions WHERE id = ?", (dataset_id,)
    ).fetchone()
    if row is None:
        raise RuntimeError(f"源结构引用的数据版本不存在: {dataset_id}")
    manifest_path = (state_root / str(row[0])).resolve()
    try:
        manifest_path.relative_to(state_root)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("id") != dataset_id:
            raise RuntimeError(f"源数据清单身份不匹配: {dataset_id}")
        storage = manifest.get("storage")
        normalized = (state_root / storage["normalized"]).resolve() if isinstance(storage, dict) else None
        if not isinstance(normalized, Path):
            raise RuntimeError(f"源数据清单缺少规范化数据路径: {dataset_id}")
        normalized.relative_to(state_root)
    except (OSError, ValueError, json.JSONDecodeError, KeyError) as error:
        raise RuntimeError(f"源数据清单或规范化路径无效: {dataset_id}") from error
    return manifest, pd.read_parquet(normalized)


def _migration_007_analysis_context_versions(connection: sqlite3.Connection) -> None:
    schema_sql = """
    CREATE TABLE IF NOT EXISTS study_context_versions (
        id TEXT PRIMARY KEY, project_id TEXT NOT NULL, revision INTEGER NOT NULL,
        schema_version TEXT NOT NULL, time_structure TEXT NOT NULL,
        dependence_structure TEXT NOT NULL, design TEXT NOT NULL,
        context_hash TEXT NOT NULL, created_at TEXT NOT NULL,
        UNIQUE(project_id, revision)
    );
    CREATE INDEX IF NOT EXISTS idx_study_context_latest ON study_context_versions(project_id, revision DESC);
    CREATE INDEX IF NOT EXISTS idx_study_context_hash ON study_context_versions(project_id, context_hash);
    CREATE TABLE IF NOT EXISTS dataset_structure_versions (
        id TEXT PRIMARY KEY, dataset_version_id TEXT NOT NULL, project_id TEXT NOT NULL,
        revision INTEGER NOT NULL, study_context_version_id TEXT NOT NULL,
        context_json TEXT NOT NULL, roles_json TEXT NOT NULL, profile_json TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('valid', 'warning', 'invalid')),
        warnings_json TEXT NOT NULL, override_reason TEXT, structure_hash TEXT NOT NULL,
        created_at TEXT NOT NULL, UNIQUE(dataset_version_id, revision),
        FOREIGN KEY(dataset_version_id) REFERENCES dataset_versions(id),
        FOREIGN KEY(study_context_version_id) REFERENCES study_context_versions(id)
    );
    CREATE INDEX IF NOT EXISTS idx_dataset_structure_latest ON dataset_structure_versions(dataset_version_id, revision DESC);
    CREATE INDEX IF NOT EXISTS idx_dataset_structure_hash ON dataset_structure_versions(dataset_version_id, structure_hash);
    CREATE TABLE IF NOT EXISTS analysis_context_snapshots (
        id TEXT PRIMARY KEY, dataset_version_id TEXT NOT NULL, context_hash TEXT NOT NULL,
        payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
        UNIQUE(dataset_version_id, context_hash),
        FOREIGN KEY(dataset_version_id) REFERENCES dataset_versions(id)
    );
    CREATE TABLE IF NOT EXISTS analysis_drafts (
        id TEXT PRIMARY KEY, dataset_version_id TEXT NOT NULL, revision INTEGER NOT NULL,
        family TEXT NOT NULL, slice_id TEXT NOT NULL, context_snapshot_id TEXT NOT NULL,
        context_hash TEXT NOT NULL, spec_json TEXT NOT NULL,
        role_overrides_json TEXT NOT NULL DEFAULT '{}',
        validity TEXT NOT NULL CHECK(validity IN ('ready','incomplete','stale','superseded')),
        invalidation_reasons_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL, FOREIGN KEY(dataset_version_id) REFERENCES dataset_versions(id),
        FOREIGN KEY(context_snapshot_id) REFERENCES analysis_context_snapshots(id)
    );
    CREATE INDEX IF NOT EXISTS idx_analysis_drafts_dataset ON analysis_drafts(dataset_version_id, updated_at DESC);
    CREATE TABLE IF NOT EXISTS imputation_plan_versions (
        id TEXT PRIMARY KEY, dataset_version_id TEXT NOT NULL, structure_version_id TEXT,
        sample_identity TEXT NOT NULL, sample_hash TEXT NOT NULL, measurement_version_id TEXT,
        context_hash TEXT NOT NULL, substantive_model_hash TEXT NOT NULL, plan_hash TEXT NOT NULL UNIQUE,
        payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
        FOREIGN KEY(dataset_version_id) REFERENCES dataset_versions(id),
        FOREIGN KEY(structure_version_id) REFERENCES dataset_structure_versions(id)
    );
    CREATE TABLE IF NOT EXISTS imputation_dataset_versions (
        id TEXT PRIMARY KEY, plan_version_id TEXT NOT NULL, job_id TEXT NOT NULL,
        artifact_manifest_path TEXT NOT NULL, artifact_hash TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('ready','failed','superseded')),
        created_at TEXT NOT NULL, FOREIGN KEY(plan_version_id) REFERENCES imputation_plan_versions(id),
        FOREIGN KEY(job_id) REFERENCES advanced_analysis_jobs(id)
    );
    CREATE TABLE IF NOT EXISTS study_plan_versions (
        id TEXT PRIMARY KEY, project_id TEXT NOT NULL, revision INTEGER NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('draft','frozen')), plan_hash TEXT NOT NULL,
        payload_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(project_id, revision)
    );
    CREATE TABLE IF NOT EXISTS study_plan_dataset_mappings (
        id TEXT PRIMARY KEY, study_plan_version_id TEXT NOT NULL, dataset_version_id TEXT NOT NULL,
        mapping_json TEXT NOT NULL, mapping_hash TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('incomplete','ready','deviated')),
        created_at TEXT NOT NULL, FOREIGN KEY(study_plan_version_id) REFERENCES study_plan_versions(id),
        FOREIGN KEY(dataset_version_id) REFERENCES dataset_versions(id)
    );
    """
    for statement in schema_sql.split(";"):
        if statement.strip():
            connection.execute(statement)
    _ensure_nullable_imputation_structure(connection)
    columns = _column_names(connection, "result_invalidations")
    for column in ("previous_context_hash", "current_context_hash", "details_json"):
        if column not in columns:
            connection.execute(f"ALTER TABLE result_invalidations ADD COLUMN {column} TEXT")
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_invalidations_identity "
        "ON result_invalidations(analysis_id, reason, current_context_hash)"
    )
    context_ids: dict[tuple[str, str], str] = {}
    context_rows = connection.execute(
        "SELECT project_id, schema_version, time_structure, dependence_structure, design, revision, updated_at "
        "FROM study_contexts ORDER BY project_id, revision"
    ).fetchall()
    for row in context_rows:
        context = {"schemaVersion": row[1], "timeStructure": row[2], "dependenceStructure": row[3], "design": row[4]}
        context_hash = canonical_sha256(context)
        context_id = "context_" + canonical_sha256(
            {"projectId": row[0], "revision": int(row[5]), "contextHash": context_hash}
        )[:32]
        connection.execute(
            "INSERT OR IGNORE INTO study_context_versions "
            "(id, project_id, revision, schema_version, time_structure, dependence_structure, design, context_hash, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (context_id, row[0], row[5], row[1], row[2], row[3], row[4], context_hash, row[6]),
        )
        context_ids[(str(row[0]), context_hash)] = context_id
    structure_rows = connection.execute(
        "SELECT ds.dataset_version_id, dv.project_id, ds.context_json, ds.subject_id, ds.cluster_id, ds.time_id, ds.revision, ds.updated_at "
        "FROM dataset_structures ds JOIN dataset_versions dv ON dv.id = ds.dataset_version_id "
        "ORDER BY ds.dataset_version_id, ds.revision"
    ).fetchall()
    for row in structure_rows:
        context = json.loads(row[2])
        context_hash = canonical_sha256(context)
        context_id = context_ids.get((str(row[1]), context_hash))
        if context_id is None:
            context_id = "context_" + canonical_sha256(
                {"projectId": row[1], "revision": 1, "contextHash": context_hash}
            )[:32]
            connection.execute(
                "INSERT INTO study_context_versions "
                "(id, project_id, revision, schema_version, time_structure, dependence_structure, design, context_hash, created_at) "
                "VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?)",
                (context_id, row[1], context["schemaVersion"], context["timeStructure"], context["dependenceStructure"], context["design"], context_hash, row[7]),
            )
            context_ids[(str(row[1]), context_hash)] = context_id
        roles = {"subjectId": row[3], "clusterId": row[4], "timeId": row[5], "groupId": None, "treatmentId": None}
        manifest, frame = _source_frame(connection, str(row[0]))
        variables = manifest.get("variables")
        if not isinstance(variables, list):
            raise RuntimeError(f"源数据清单缺少变量字典: {row[0]}")
        names = {str(item["id"]): str(item["originalName"]) for item in variables if isinstance(item, dict) and "id" in item and "originalName" in item}
        profile_roles = {role: names.get(value) if isinstance(value, str) else None for role, value in roles.items()}
        profile, status, warnings = profile_structure(frame, profile_roles)
        payload = {"datasetVersionId": row[0], "contextSnapshot": context, "roles": roles, "profileStatus": status, "overrideReason": None}
        structure_hash = canonical_sha256(payload)
        structure_id = "structure_" + canonical_sha256(
            {"datasetVersionId": row[0], "revision": int(row[6]), "structureHash": structure_hash}
        )[:32]
        connection.execute(
            "INSERT OR IGNORE INTO dataset_structure_versions "
            "(id, dataset_version_id, project_id, revision, study_context_version_id, context_json, roles_json, profile_json, status, warnings_json, override_reason, structure_hash, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (structure_id, row[0], row[1], row[6], context_id, json.dumps(context, ensure_ascii=False, sort_keys=True), json.dumps(roles, ensure_ascii=False, sort_keys=True), json.dumps(profile, ensure_ascii=False, sort_keys=True), status, json.dumps(warnings, ensure_ascii=False, sort_keys=True), None, structure_hash, row[7]),
        )
