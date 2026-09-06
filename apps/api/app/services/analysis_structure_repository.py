from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Protocol, cast

import pandas as pd

from app.services.canonical_identity import canonical_sha256
from app.services.repository_io import _utc_now
from app.services.study_structure_profile import profile_structure


class _DatasetPathProvider(Protocol):
    def get_dataset_data_path(self, dataset_id: str) -> Path: ...


class AnalysisStructureRepositoryMixin:
    """Persistence for immutable dataset structure versions."""

    settings: object

    def _connect(self) -> sqlite3.Connection:
        raise NotImplementedError

    def _dataset_row(self, dataset_id: str) -> sqlite3.Row:
        raise NotImplementedError

    def get_dataset(self, dataset_id: str) -> dict[str, object]:
        raise NotImplementedError

    def _context_version_for_input(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        context: dict[str, object],
        created_at: str,
    ) -> dict[str, object]:
        raise NotImplementedError

    @staticmethod
    def _structure_id(dataset_id: str, revision: int, structure_hash: str) -> str:
        return "structure_" + canonical_sha256(
            {"datasetVersionId": dataset_id, "revision": revision, "structureHash": structure_hash}
        )[:32]

    def _structure_response(self, row: sqlite3.Row) -> dict[str, object]:
        roles = cast(dict[str, object], json.loads(row["roles_json"]))
        return {
            "datasetVersionId": row["dataset_version_id"],
            "projectId": row["project_id"],
            "context": json.loads(row["context_json"]),
            **roles,
            "id": row["id"],
            "revision": row["revision"],
            "studyContextVersionId": row["study_context_version_id"],
            "profile": json.loads(row["profile_json"]),
            "status": row["status"],
            "warnings": json.loads(row["warnings_json"]),
            "overrideReason": row["override_reason"],
            "structureHash": row["structure_hash"],
            "createdAt": row["created_at"],
            "updatedAt": row["created_at"],
        }

    def _structure_version_response(self, row: sqlite3.Row) -> dict[str, object]:
        return {
            "schemaVersion": "1.0.0",
            "id": row["id"],
            "datasetVersionId": row["dataset_version_id"],
            "projectId": row["project_id"],
            "revision": row["revision"],
            "studyContextVersionId": row["study_context_version_id"],
            "contextSnapshot": json.loads(row["context_json"]),
            "roles": json.loads(row["roles_json"]),
            "profile": json.loads(row["profile_json"]),
            "status": row["status"],
            "warnings": json.loads(row["warnings_json"]),
            "overrideReason": row["override_reason"],
            "structureHash": row["structure_hash"],
            "createdAt": row["created_at"],
        }

    def _latest_structure_row(
        self, connection: sqlite3.Connection, dataset_id: str
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM dataset_structure_versions "
            "WHERE dataset_version_id = ? ORDER BY revision DESC LIMIT 1",
            (dataset_id,),
        ).fetchone()

    @staticmethod
    def _normalized_structure_roles(
        context: dict[str, object], roles: dict[str, object]
    ) -> dict[str, object]:
        role_keys = ("subjectId", "clusterId", "timeId", "groupId", "treatmentId")
        normalized: dict[str, object] = {role: roles.get(role) for role in role_keys}
        if context.get("timeStructure") == "panel":
            data_layout = roles.get("dataLayout") or "long"
            if data_layout not in {"long", "wide"}:
                raise ValueError("STRUCTURE_LAYOUT_INVALID: panel dataLayout 必须是 long 或 wide")
            normalized["dataLayout"] = data_layout
            normalized["waveCount"] = roles.get("waveCount")
        else:
            normalized["dataLayout"] = "long"
            normalized["waveCount"] = None
        return normalized

    def _structure_inputs(
        self,
        dataset_id: str,
        context: dict[str, object],
        roles: dict[str, object],
    ) -> tuple[dict[str, object], str, list[dict[str, str]], str]:
        dataset = self.get_dataset(dataset_id)
        variables = cast(list[dict[str, object]], dataset["variables"])
        known_ids = {str(variable["id"]) for variable in variables}
        normalized_roles = self._normalized_structure_roles(context, roles)
        assigned = {
            role: value
            for role, value in normalized_roles.items()
            if role in {"subjectId", "clusterId", "timeId", "groupId", "treatmentId"}
            if isinstance(value, str) and value
        }
        unknown = sorted(set(assigned.values()) - known_ids)
        if unknown:
            raise ValueError("DATA_STRUCTURE_UNKNOWN_VARIABLES: " + ", ".join(unknown))
        required: list[tuple[str, object]] = []
        if context["timeStructure"] == "intensive_longitudinal":
            required.extend(
                [("subjectId", normalized_roles["subjectId"]), ("timeId", normalized_roles["timeId"])]
            )
        elif context["timeStructure"] == "panel":
            required.append(("subjectId", normalized_roles["subjectId"]))
            if normalized_roles["dataLayout"] == "long":
                required.append(("timeId", normalized_roles["timeId"]))
            else:
                wave_count = normalized_roles["waveCount"]
                if not isinstance(wave_count, int) or isinstance(wave_count, bool) or not 2 <= wave_count <= 10:
                    raise ValueError("STRUCTURE_WAVE_COUNT_REQUIRED: 宽格式 panel 必须声明 2 到 10 个波次")
        if context["dependenceStructure"] == "nested":
            required.append(("clusterId", normalized_roles["clusterId"]))
        if context["design"] in {"randomized", "quasi_experimental"} and not (
            normalized_roles["groupId"] or normalized_roles["treatmentId"]
        ):
            raise ValueError("STRUCTURE_GROUP_OR_TREATMENT_REQUIRED: 随机实验或非随机比较至少需要 groupId 或 treatmentId")
        missing = [role for role, value in required if not value]
        if missing:
            raise ValueError("STRUCTURE_ROLE_REQUIRED: " + ", ".join(missing))
        structural_values = [
            normalized_roles[role]
            for role in ("subjectId", "clusterId", "timeId", "groupId", "treatmentId")
            if normalized_roles[role]
        ]
        if len(structural_values) != len(set(structural_values)):
            raise ValueError("STRUCTURE_ROLE_INVALID: 结构角色变量必须不同")
        variable_names = {
            str(variable["id"]): str(variable["originalName"])
            for variable in variables
        }
        profile_roles: dict[str, str | None] = {}
        for role in ("subjectId", "clusterId", "timeId", "groupId", "treatmentId"):
            variable_id = normalized_roles[role]
            profile_roles[role] = variable_names.get(variable_id) if isinstance(variable_id, str) else None
        frame = pd.read_parquet(
            cast(_DatasetPathProvider, self).get_dataset_data_path(dataset_id)
        )
        profile, status, warnings = profile_structure(
            frame,
            profile_roles,
            data_layout=str(normalized_roles["dataLayout"]),
            wave_count=normalized_roles["waveCount"] if isinstance(normalized_roles["waveCount"], int) else None,
        )
        structure_payload = {
            "datasetVersionId": dataset_id,
            "contextSnapshot": context,
            "roles": normalized_roles,
            "profileStatus": status,
            "overrideReason": None,
        }
        return profile, status, warnings, canonical_sha256(structure_payload)

    def validate_dataset_structure(
        self,
        dataset_id: str,
        study_context_version_id: str,
        roles: dict[str, object],
    ) -> dict[str, object]:
        dataset = self.get_dataset(dataset_id)
        with self._connect() as connection:
            context_row = connection.execute(
                "SELECT * FROM study_context_versions WHERE id = ? AND project_id = ?",
                (study_context_version_id, dataset["projectId"]),
            ).fetchone()
        if context_row is None:
            raise ValueError("ANALYSIS_CONTEXT_INCOMPLETE: studyContextVersionId 不属于当前项目")
        context = {
            "schemaVersion": context_row["schema_version"],
            "timeStructure": context_row["time_structure"],
            "dependenceStructure": context_row["dependence_structure"],
            "design": context_row["design"],
        }
        profile, status, warnings, structure_hash = self._structure_inputs(
            dataset_id, context, roles
        )
        return {
            "status": status,
            "profile": profile,
            "warnings": warnings,
            "proposedStructureHash": structure_hash,
        }

    def save_dataset_structure_version(
        self,
        dataset_id: str,
        study_context_version_id: str,
        roles: dict[str, object],
        override_reason: str | None,
        expected_revision: int | None,
    ) -> dict[str, object]:
        dataset = self.get_dataset(dataset_id)
        with self._connect() as connection:
            context_row = connection.execute(
                "SELECT * FROM study_context_versions WHERE id = ? AND project_id = ?",
                (study_context_version_id, dataset["projectId"]),
            ).fetchone()
            latest = self._latest_structure_row(connection, dataset_id)
        if context_row is None:
            raise ValueError("ANALYSIS_CONTEXT_INCOMPLETE: studyContextVersionId 不属于当前项目")
        current_revision = None if latest is None else int(latest["revision"])
        if expected_revision != current_revision:
            raise ValueError("REVISION_CONFLICT: expectedRevision 与当前结构版本不一致")
        context = {
            "schemaVersion": context_row["schema_version"],
            "timeStructure": context_row["time_structure"],
            "dependenceStructure": context_row["dependence_structure"],
            "design": context_row["design"],
        }
        profile, status, warnings, _ = self._structure_inputs(dataset_id, context, roles)
        if status == "warning":
            if not isinstance(override_reason, str):
                raise ValueError("STRUCTURE_WARNING_OVERRIDE_REQUIRED: 质量警告需要填写继续原因")
            if not 10 <= len(override_reason) <= 1000:
                raise ValueError("STRUCTURE_WARNING_OVERRIDE_REQUIRED: 继续原因长度必须为 10 到 1000 字")
        if status == "invalid":
            raise ValueError("STRUCTURE_ROLE_INVALID: 数据结构画像未通过最低要求")
        normalized_roles = self._normalized_structure_roles(context, roles)
        structure_payload = {
            "datasetVersionId": dataset_id,
            "contextSnapshot": context,
            "roles": normalized_roles,
            "profileStatus": status,
            "overrideReason": override_reason,
        }
        structure_hash = canonical_sha256(structure_payload)
        with self._connect() as connection:
            latest = self._latest_structure_row(connection, dataset_id)
            if latest is not None and latest["structure_hash"] == structure_hash:
                return self._structure_version_response(latest)
            revision = 1 if latest is None else int(latest["revision"]) + 1
            created_at = _utc_now()
            structure_id = self._structure_id(dataset_id, revision, structure_hash)
            connection.execute(
                "INSERT INTO dataset_structure_versions "
                "(id, dataset_version_id, project_id, revision, study_context_version_id, "
                "context_json, roles_json, profile_json, status, warnings_json, override_reason, "
                "structure_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    structure_id,
                    dataset_id,
                    dataset["projectId"],
                    revision,
                    study_context_version_id,
                    json.dumps(context, ensure_ascii=False, sort_keys=True),
                    json.dumps(normalized_roles, ensure_ascii=False, sort_keys=True),
                    json.dumps(profile, ensure_ascii=False, sort_keys=True),
                    status,
                    json.dumps(warnings, ensure_ascii=False, sort_keys=True),
                    override_reason,
                    structure_hash,
                    created_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM dataset_structure_versions WHERE id = ?", (structure_id,)
            ).fetchone()
        assert row is not None
        return self._structure_version_response(row)

    def get_dataset_structure(self, dataset_id: str) -> dict[str, object] | None:
        self._dataset_row(dataset_id)
        with self._connect() as connection:
            row = self._latest_structure_row(connection, dataset_id)
        return None if row is None else self._structure_response(row)

    def save_dataset_structure(
        self,
        dataset_id: str,
        structure: dict[str, object],
        *,
        allow_existing_warning_override: bool = False,
    ) -> dict[str, object]:
        dataset = self.get_dataset(dataset_id)
        context = cast(dict[str, object], structure["context"])
        roles = {
            role: structure.get(role)
            for role in ("subjectId", "clusterId", "timeId", "groupId", "treatmentId", "dataLayout", "waveCount")
        }
        override_reason = structure.get("overrideReason")
        if allow_existing_warning_override and override_reason is None:
            override_reason = "保存时已确认知晓结构质量警告"
        with self._connect() as connection:
            context_version = self._context_version_for_input(connection, str(dataset["projectId"]), context, _utc_now())
            latest = self._latest_structure_row(connection, dataset_id)
            expected_revision = None if latest is None else int(latest["revision"])
        saved = self.save_dataset_structure_version(
            dataset_id, str(context_version["id"]), roles, cast(str | None, override_reason), expected_revision
        )
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM dataset_structure_versions WHERE id = ?", (saved["id"],)
            ).fetchone()
        assert row is not None
        return self._structure_response(row)
