import json
import os
import sqlite3
import stat

import pytest

from jobsearch_mcp.backup import BACKUP_NAME, BackupError, create_backup, main


def _open_live_wal_database(path):
    """Create realistic store tables and leave committed rows in the WAL."""
    database = sqlite3.connect(path)
    assert database.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
    database.execute("PRAGMA wal_autocheckpoint=0")
    database.executescript(
        """
        CREATE TABLE jobs (id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE profile (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);
        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            job_id TEXT NOT NULL,
            at TEXT NOT NULL,
            old_status TEXT,
            new_status TEXT NOT NULL,
            reason TEXT NOT NULL
        );
        """
    )
    database.execute(
        "INSERT INTO jobs VALUES(?, ?)",
        ("job-1", json.dumps({"title": "WAL_JOB_SENTINEL"})),
    )
    database.execute(
        "INSERT INTO profile VALUES(1, ?)",
        (json.dumps({"resume_text": "WAL_PROFILE_SENTINEL"}),),
    )
    database.execute(
        "INSERT INTO events(job_id, at, new_status, reason) VALUES(?, ?, ?, ?)",
        ("job-1", "2026-09-19T12:00:00Z", "discovered", "WAL_EVENT_SENTINEL"),
    )
    database.commit()
    assert os.path.getsize(f"{path}-wal") > 32
    return database


def _owned_backups(directory):
    return sorted(path for path in directory.iterdir() if BACKUP_NAME.fullmatch(path.name))


def test_backup_api_captures_committed_wal_jobs_profile_and_events(tmp_path):
    source_path = tmp_path / "live.sqlite3"
    live_database = _open_live_wal_database(source_path)
    try:
        backup_path = create_backup(source_path, tmp_path / "backups")
    finally:
        live_database.close()

    with sqlite3.connect(backup_path) as backup:
        assert backup.execute("SELECT id, data FROM jobs").fetchone() == (
            "job-1",
            '{"title": "WAL_JOB_SENTINEL"}',
        )
        assert backup.execute("SELECT data FROM profile WHERE id=1").fetchone() == (
            '{"resume_text": "WAL_PROFILE_SENTINEL"}',
        )
        assert backup.execute("SELECT reason FROM events").fetchone() == ("WAL_EVENT_SENTINEL",)
        assert backup.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_failed_sources_preserve_valid_backups_and_do_not_prune(tmp_path):
    source_path = tmp_path / "valid.sqlite3"
    live_database = _open_live_wal_database(source_path)
    live_database.close()
    backup_directory = tmp_path / "backups"
    first = create_backup(source_path, backup_directory, keep=5)
    second = create_backup(source_path, backup_directory, keep=5)
    original_bytes = {path: path.read_bytes() for path in (first, second)}

    missing_source = tmp_path / "missing.sqlite3"
    with pytest.raises(BackupError):
        create_backup(missing_source, backup_directory, keep=1)
    assert not missing_source.exists()

    invalid_source = tmp_path / "invalid.sqlite3"
    invalid_source.write_text("not a SQLite database", encoding="utf-8")
    with pytest.raises(BackupError):
        create_backup(invalid_source, backup_directory, keep=1)

    assert _owned_backups(backup_directory) == sorted((first, second))
    assert {path: path.read_bytes() for path in (first, second)} == original_bytes
    assert not list(backup_directory.glob(".*.tmp"))


def test_retention_removes_only_owned_backups_and_directory_and_files_are_private(tmp_path):
    source_path = tmp_path / "valid.sqlite3"
    live_database = _open_live_wal_database(source_path)
    live_database.close()
    backup_directory = tmp_path / "backups"
    backup_directory.mkdir()
    backup_directory.chmod(0o755)
    unrelated_file = backup_directory / "keep-me.sqlite3"
    unrelated_file.write_text("user data", encoding="utf-8")
    unrelated_prefix_file = backup_directory / "career-search-backup-not-owned.sqlite3"
    unrelated_prefix_file.write_text("user data", encoding="utf-8")

    for _ in range(4):
        create_backup(source_path, backup_directory, keep=2)

    backups = _owned_backups(backup_directory)
    assert len(backups) == 2
    assert unrelated_file.read_text(encoding="utf-8") == "user data"
    assert unrelated_prefix_file.read_text(encoding="utf-8") == "user data"
    assert stat.S_IMODE(backup_directory.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in backups)
    assert not list(backup_directory.glob(".*.tmp"))


def test_cli_reports_status_and_path_without_database_contents(tmp_path, capsys):
    source_path = tmp_path / "private.sqlite3"
    live_database = _open_live_wal_database(source_path)
    live_database.close()
    backup_directory = tmp_path / "backups"

    result = main(
        ["--database", str(source_path), "--directory", str(backup_directory), "--keep", "1"]
    )

    output = capsys.readouterr()
    assert result == 0
    assert "status=ok" in output.out
    assert "backups=1" in output.out
    assert "WAL_JOB_SENTINEL" not in output.out
    assert "WAL_PROFILE_SENTINEL" not in output.out
    assert "WAL_EVENT_SENTINEL" not in output.out
    assert output.err == ""


def test_keep_must_be_at_least_one(tmp_path):
    with pytest.raises(ValueError, match="keep must be at least 1"):
        create_backup(tmp_path / "missing.sqlite3", tmp_path / "backups", keep=0)
