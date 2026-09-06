from __future__ import annotations

import json
import sqlite3

from app.services.analysis_structure_repository import AnalysisStructureRepositoryMixin
from app.services.canonical_identity import canonical_sha256
from app.services.repository_io import _utc_now
from app.settings import Settings


class AnalysisContextRepositoryMixin(AnalysisStructureRepositoryMixin):
    """Persistence for immutable context and structure versions.

    ``study_contexts`` and ``dataset_structures`` retain a recovery projection.
    Authoritative reads and writes use the immutable version tables.
    """

    settings: Settings

    def _connect(self) -> sqlite3.Connection:
        raise NotImplementedError

    def _dataset_row(self, dataset_id: str) -> sqlite3.Row:
        raise NotImplementedError

    def get_dataset(self, dataset_id: str) -> dict[str, object]:
        raise NotImplementedError

    @staticmethod
    def _context_hash(context: dict[str, object]) -> str:
        return canonical_sha256(
            {
                "schemaVersion": context["schemaVersion"],
                "timeStructure": context["timeStructure"],
                "dependenceStructure": context["dependenceStructure"],
                "design": context["design"],
            }
        )

    @staticmethod
    def _context_id(project_id: str, revision: int, context_hash: str) -> str:
        return "context_" + canonical_sha256(
            {"projectId": project_id, "revision": revision, "contextHash": context_hash}
        )[:32]

    def _insert_context_version(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        context: dict[str, object],
        revision: int,
        created_at: str,
    ) -> dict[str, object]:
        context_hash = self._context_hash(context)
        context_id = self._context_id(project_id, revision, context_hash)
        connection.execute(
            "INSERT INTO study_context_versions "
            "(id, project_id, revision, schema_version, time_structure, dependence_structure, "
            "design, context_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                context_id,
                project_id,
                revision,
                context["schemaVersion"],
                context["timeStructure"],
                context["dependenceStructure"],
                context["design"],
                context_hash,
                created_at,
            ),
        )
        return {
            "schemaVersion": context["schemaVersion"],
            "projectId": project_id,
            "timeStructure": context["timeStructure"],
            "dependenceStructure": context["dependenceStructure"],
            "design": context["design"],
            "revision": revision,
            "id": context_id,
            "contextHash": context_hash,
            "createdAt": created_at,
        }

    def _latest_context_row(self, connection: sqlite3.Connection, project_id: str) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM study_context_versions "
            "WHERE project_id = ? ORDER BY revision DESC LIMIT 1",
            (project_id,),
        ).fetchone()

    @staticmethod
    def _context_row_response(row: sqlite3.Row) -> dict[str, object]:
        return {
            "schemaVersion": row["schema_version"],
            "projectId": row["project_id"],
            "timeStructure": row["time_structure"],
            "dependenceStructure": row["dependence_structure"],
            "design": row["design"],
            "revision": row["revision"],
            "id": row["id"],
            "contextHash": row["context_hash"],
            "createdAt": row["created_at"],
        }

    def get_study_context(self, project_id: str) -> dict[str, object] | None:
        with self._connect() as connection:
            row = self._latest_context_row(connection, project_id)
        return None if row is None else self._context_row_response(row)

    def list_study_context_versions(self, project_id: str) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM study_context_versions "
                "WHERE project_id = ? ORDER BY revision DESC",
                (project_id,),
            ).fetchall()
        return [self._context_row_response(row) for row in rows]

    def get_study_context_version(
        self, project_id: str, context_id: str
    ) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM study_context_versions WHERE project_id = ? AND id = ?",
                (project_id, context_id),
            ).fetchone()
        return None if row is None else self._context_row_response(row)

    def get_imputation_dataset(
        self, dataset_id: str, imputation_dataset_id: str
    ) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT d.id, d.artifact_hash, d.status "
                "FROM imputation_dataset_versions d "
                "JOIN imputation_plan_versions p ON p.id = d.plan_version_id "
                "WHERE d.id = ? AND p.dataset_version_id = ?",
                (imputation_dataset_id, dataset_id),
            ).fetchone()
        if row is None:
            return None
        return {"id": row["id"], "hash": row["artifact_hash"], "status": row["status"]}

    def save_analysis_context_snapshot(
        self, dataset_id: str, context: dict[str, object]
    ) -> str:
        context_hash = str(context["contextHash"])
        snapshot_id = "snapshot_" + canonical_sha256(
            {"datasetVersionId": dataset_id, "contextHash": context_hash}
        )[:32]
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO analysis_context_snapshots "
                "(id, dataset_version_id, context_hash, payload_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    snapshot_id,
                    dataset_id,
                    context_hash,
                    json.dumps(context, ensure_ascii=False, sort_keys=True),
                    _utc_now(),
                ),
            )
        return snapshot_id

    def save_study_context(
        self, project_id: str, context: dict[str, object]
    ) -> dict[str, object]:
        created_at = _utc_now()
        with self._connect() as connection:
            latest = self._latest_context_row(connection, project_id)
            revision = 1 if latest is None else int(latest["revision"]) + 1
            saved = self._insert_context_version(
                connection, project_id, context, revision, created_at
            )
        return saved

    def save_study_context_version(
        self,
        project_id: str,
        context: dict[str, object],
        expected_revision: int | None,
    ) -> dict[str, object]:
        created_at = _utc_now()
        context_hash = self._context_hash(context)
        with self._connect() as connection:
            latest = self._latest_context_row(connection, project_id)
            current_revision = None if latest is None else int(latest["revision"])
            if expected_revision != current_revision:
                raise ValueError(
                    "REVISION_CONFLICT: expectedRevision 与当前上下文版本不一致"
                )
            if latest is not None and latest["context_hash"] == context_hash:
                return self._context_row_response(latest)
            revision = 1 if latest is None else int(latest["revision"]) + 1
            return self._insert_context_version(
                connection, project_id, context, revision, created_at
            )

    def _context_version_for_input(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        context: dict[str, object],
        created_at: str,
    ) -> dict[str, object]:
        context_hash = self._context_hash(context)
        row = connection.execute(
            "SELECT * FROM study_context_versions "
            "WHERE project_id = ? AND context_hash = ? ORDER BY revision DESC LIMIT 1",
            (project_id, context_hash),
        ).fetchone()
        if row is not None:
            return self._context_row_response(row)
        latest = self._latest_context_row(connection, project_id)
        revision = 1 if latest is None else int(latest["revision"]) + 1
        return self._insert_context_version(
            connection, project_id, context, revision, created_at
        )
