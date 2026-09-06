from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from app.services.dataset_repository import DatasetRepository
from app.services.study_context_repository import StudyContextRepositoryMixin
from app.settings import Settings, get_settings


def _repository(tmp_path: Path) -> DatasetRepository:
    return DatasetRepository(replace(get_settings(), state_root=tmp_path / "state"))


class LegacyOnlyStudyContextRepository(StudyContextRepositoryMixin):
    """Exercises the base mixin without repository MRO overrides."""

    def __init__(self, backing: DatasetRepository) -> None:
        self.settings: Settings = backing.settings
        self._backing = backing
        self.database_path = backing.database_path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _dataset_row(self, dataset_id: str) -> sqlite3.Row:
        return self._backing._dataset_row(dataset_id)

    def get_dataset(self, dataset_id: str) -> dict[str, object]:
        return self._backing.get_dataset(dataset_id)


def _insert_dataset(repository: DatasetRepository, dataset_id: str) -> None:
    dataset_dir = repository.settings.state_root / "projects/default/datasets" / dataset_id
    dataset_dir.mkdir(parents=True)
    (dataset_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": dataset_id,
                "variables": [
                    {"id": "var_1", "label": "subject"},
                    {"id": "var_2", "label": "time"},
                ],
            }
        ),
        encoding="utf-8",
    )
    with repository._connect() as connection:
        connection.execute(
            """
            INSERT INTO dataset_versions (
                id, project_id, created_at, original_name, file_format,
                sha256, manifest_path, row_count, column_count,
                current_dictionary_version
            ) VALUES (?, 'default', '2026-08-16', 'input.csv', 'csv', ?, ?, 2, 2, 0)
            """,
            (dataset_id, "0" * 64, f"projects/default/datasets/{dataset_id}/manifest.json"),
        )


_CONTEXT: dict[str, object] = {
    "schemaVersion": "1.0.0",
    "projectId": "default",
    "timeStructure": "cross_sectional",
    "dependenceStructure": "independent",
    "design": "observational",
}


def test_study_context_round_trip_and_revision_increment(tmp_path: Path) -> None:
    backing = _repository(tmp_path)
    repository = LegacyOnlyStudyContextRepository(backing)
    assert repository.get_study_context("default") is None

    first = repository.save_study_context("default", _CONTEXT)
    assert first["revision"] == 1
    assert first["timeStructure"] == "cross_sectional"

    second = repository.save_study_context(
        "default",
        {**_CONTEXT, "timeStructure": "panel", "dependenceStructure": "independent"},
    )
    assert second["revision"] == 2
    assert second["timeStructure"] == "panel"
    assert repository.get_study_context("default") == second


def test_dataset_structure_round_trip_validates_variable_ids(tmp_path: Path) -> None:
    backing = _repository(tmp_path)
    _insert_dataset(backing, "dataset_a")
    repository = LegacyOnlyStudyContextRepository(backing)
    assert repository.get_dataset_structure("dataset_a") is None

    structure = {
        "datasetVersionId": "dataset_a",
        "context": _CONTEXT,
        "subjectId": "var_1",
        "clusterId": None,
        "timeId": None,
    }
    first = repository.save_dataset_structure("dataset_a", structure)
    assert first["revision"] == 1
    assert first["subjectId"] == "var_1"
    assert isinstance(first["context"], dict)

    with pytest.raises(ValueError, match="DATA_STRUCTURE_UNKNOWN_VARIABLES"):
        repository.save_dataset_structure(
            "dataset_a", {**structure, "subjectId": "var_unknown"}
        )
