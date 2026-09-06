from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from io import BytesIO
from zipfile import ZIP_BZIP2, ZIP_DEFLATED, ZipFile

import pytest

from app.services import workspace_archive
from app.services.database_migrations import CURRENT_DATABASE_VERSION
from app.services.dataset_import import import_dataset
from app.services.dataset_repository import DatasetRepository
from app.services.workspace_archive import (
    MANIFEST_NAME,
    WorkspaceArchiveError,
    create_workspace_backup,
    drill_workspace_backup,
    restore_workspace_backup,
    verify_workspace_backup,
)
from app.settings import get_settings


def test_workspace_backup_verify_and_isolated_restore_round_trip(tmp_path) -> None:
    settings = replace(get_settings(), state_root=tmp_path / "workspace")
    DatasetRepository(settings)
    evidence = settings.state_root / "projects/default/evidence.txt"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("original evidence", encoding="utf-8")
    archive = tmp_path / "backup.zip"

    created = create_workspace_backup(settings.state_root, archive)
    verified = verify_workspace_backup(archive)
    assert created["valid"] is True
    assert verified["archiveSha256"] == created["archiveSha256"]
    assert verified["databaseUserVersion"] == CURRENT_DATABASE_VERSION
    drill = drill_workspace_backup(archive)
    assert drill["recoveryDrill"] == "passed"
    assert drill["databaseQuickCheck"] == ["ok"]
    assert drill["foreignKeyViolations"] == []

    evidence.write_text("mutated after backup", encoding="utf-8")
    restored = tmp_path / "restored-workspace"
    result = restore_workspace_backup(archive, restored)
    assert result["valid"] is True
    assert (restored / "projects/default/evidence.txt").read_text(
        encoding="utf-8"
    ) == "original evidence"
    restored_repository = DatasetRepository(replace(settings, state_root=restored))
    with restored_repository._connect() as connection:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_version_one_project_archive_restores_and_migrates_with_data(tmp_path) -> None:
    settings = replace(get_settings(), state_root=tmp_path / "source-workspace")
    repository = DatasetRepository(settings)
    dataset = import_dataset(
        BytesIO(b"respondent_id,score\n1,3.5\n2,4.0\n"),
        "source.csv",
        settings,
        repository,
    )
    database_path = settings.state_root / "metadata.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            ALTER TABLE analysis_jobs RENAME TO analysis_jobs_v2;
            CREATE TABLE analysis_jobs (
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
            DROP TABLE analysis_jobs_v2;
            DELETE FROM schema_migrations WHERE version >= 2;
            PRAGMA user_version = 1;
            """
        )

    archive = tmp_path / "version-one-project.zip"
    created = create_workspace_backup(settings.state_root, archive)
    assert created["databaseUserVersion"] == 1
    restored = tmp_path / "restored-workspace"
    restore_workspace_backup(archive, restored)

    migrated = DatasetRepository(replace(settings, state_root=restored))
    loaded = migrated.get_dataset(dataset["id"])
    assert loaded["originalFile"]["name"] == "source.csv"
    assert loaded["rowCount"] == 2
    with migrated._connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == (CURRENT_DATABASE_VERSION)
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"


def test_restore_refuses_existing_target_and_archive_path_traversal(tmp_path) -> None:
    state_root = tmp_path / "workspace"
    settings = replace(get_settings(), state_root=state_root)
    DatasetRepository(settings)
    archive = tmp_path / "backup.zip"
    create_workspace_backup(state_root, archive)
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(WorkspaceArchiveError, match="必须不存在"):
        restore_workspace_backup(archive, existing)

    unsafe = tmp_path / "unsafe.zip"
    manifest = {
        "schemaVersion": "1.0.0",
        "createdAt": "2026-07-14T00:00:00+00:00",
        "databaseUserVersion": None,
        "fileCount": 1,
        "files": [{"path": "../escape", "sizeBytes": 1, "sha256": "0" * 64}],
    }
    with ZipFile(unsafe, "w", compression=ZIP_DEFLATED) as target:
        target.writestr(MANIFEST_NAME, json.dumps(manifest))
        target.writestr("../escape", b"x")
    with pytest.raises(WorkspaceArchiveError, match="不安全路径"):
        verify_workspace_backup(unsafe)


@pytest.mark.parametrize("member", [r"\Windows\Temp\owned", r"C:\outside", r"\\server\share\owned"])
def test_archive_rejects_windows_rooted_member_names(tmp_path, member: str) -> None:
    archive_path = tmp_path / "windows-path.zip"
    manifest = {
        "schemaVersion": "1.0.0",
        "createdAt": "2026-07-14T00:00:00+00:00",
        "databaseUserVersion": None,
        "fileCount": 1,
        "files": [{"path": member, "sizeBytes": 1, "sha256": "0" * 64}],
    }
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as target:
        target.writestr(MANIFEST_NAME, json.dumps(manifest))
        target.writestr(member, b"x")
    with pytest.raises(WorkspaceArchiveError, match="不安全路径"):
        verify_workspace_backup(archive_path)


def _write_single_member_archive(
    archive_path,
    payload: bytes,
    *,
    compression: int = ZIP_DEFLATED,
) -> None:
    manifest = {
        "schemaVersion": "1.0.0",
        "createdAt": "2026-07-15T00:00:00+00:00",
        "databaseUserVersion": None,
        "fileCount": 1,
        "files": [
            {
                "path": "payload.bin",
                "sizeBytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        ],
    }
    with ZipFile(archive_path, "w", compression=compression) as target:
        target.writestr(MANIFEST_NAME, json.dumps(manifest))
        target.writestr("payload.bin", payload)


def test_archive_enforces_member_total_ratio_and_compression_budgets(tmp_path, monkeypatch) -> None:
    archive_path = tmp_path / "bounded.zip"
    _write_single_member_archive(archive_path, b"123456789")
    monkeypatch.setattr(workspace_archive, "MAX_ARCHIVE_BYTES", 1)
    with pytest.raises(WorkspaceArchiveError, match="压缩文件大小"):
        verify_workspace_backup(archive_path)

    monkeypatch.setattr(workspace_archive, "MAX_ARCHIVE_BYTES", 1024 * 1024)
    monkeypatch.setattr(workspace_archive, "MAX_ARCHIVE_ENTRIES", 1)
    with pytest.raises(WorkspaceArchiveError, match="成员数量"):
        verify_workspace_backup(archive_path)

    monkeypatch.setattr(workspace_archive, "MAX_ARCHIVE_ENTRIES", 10_000)
    monkeypatch.setattr(workspace_archive, "MAX_MEMBER_BYTES", 8)
    with pytest.raises(WorkspaceArchiveError, match="大小不合法|展开大小限制"):
        verify_workspace_backup(archive_path)

    monkeypatch.setattr(workspace_archive, "MAX_MEMBER_BYTES", 1024)
    monkeypatch.setattr(workspace_archive, "MAX_TOTAL_EXPANDED_BYTES", 8)
    with pytest.raises(WorkspaceArchiveError, match="总展开大小"):
        verify_workspace_backup(archive_path)

    ratio_archive = tmp_path / "ratio.zip"
    _write_single_member_archive(ratio_archive, b"0" * 1000)
    monkeypatch.setattr(workspace_archive, "MAX_TOTAL_EXPANDED_BYTES", 2048)
    monkeypatch.setattr(workspace_archive, "MAX_COMPRESSION_RATIO", 2)
    with pytest.raises(WorkspaceArchiveError, match="压缩比过高"):
        verify_workspace_backup(ratio_archive)

    unsupported = tmp_path / "unsupported.zip"
    _write_single_member_archive(unsupported, b"payload", compression=ZIP_BZIP2)
    monkeypatch.setattr(workspace_archive, "MAX_COMPRESSION_RATIO", 1000)
    with pytest.raises(WorkspaceArchiveError, match="不支持的压缩算法"):
        verify_workspace_backup(unsupported)


def test_restore_revalidates_resource_limits_after_preflight(tmp_path, monkeypatch) -> None:
    archive_path = tmp_path / "swapped-after-verify.zip"
    _write_single_member_archive(archive_path, b"123456789")
    monkeypatch.setattr(
        workspace_archive,
        "verify_workspace_backup",
        lambda _path: {
            "valid": True,
            "archiveSha256": "0" * 64,
            "fileCount": 1,
            "databaseUserVersion": None,
            "createdAt": "2026-07-15T00:00:00+00:00",
        },
    )
    monkeypatch.setattr(workspace_archive, "MAX_MEMBER_BYTES", 8)

    target = tmp_path / "restored"
    with pytest.raises(WorkspaceArchiveError, match="展开大小限制"):
        restore_workspace_backup(archive_path, target)
    assert not target.exists()


def test_archive_rejects_non_string_manifest_path(tmp_path) -> None:
    archive_path = tmp_path / "invalid-manifest-path.zip"
    manifest = {
        "schemaVersion": "1.0.0",
        "createdAt": "2026-07-15T00:00:00+00:00",
        "databaseUserVersion": None,
        "fileCount": 1,
        "files": [{"path": 123, "sizeBytes": 1, "sha256": "0" * 64}],
    }
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as target:
        target.writestr(MANIFEST_NAME, json.dumps(manifest))
        target.writestr("123", b"x")

    with pytest.raises(WorkspaceArchiveError, match="无效文件条目"):
        verify_workspace_backup(archive_path)


def test_backup_rejects_file_count_before_writing_archive(tmp_path, monkeypatch) -> None:
    state_root = tmp_path / "workspace"
    settings = replace(get_settings(), state_root=state_root)
    DatasetRepository(settings)
    archive_path = tmp_path / "too-many-files.zip"
    monkeypatch.setattr(workspace_archive, "MAX_ARCHIVE_ENTRIES", 1)

    with pytest.raises(WorkspaceArchiveError, match="文件数量"):
        create_workspace_backup(state_root, archive_path)
    assert not archive_path.exists()
