"""Create private, consistent SQLite backups for the local career search store."""

import argparse
import os
import re
import sqlite3
import sys
import tempfile
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

BACKUP_PREFIX = "career-search-backup-"
BACKUP_SUFFIX = ".sqlite3"
BACKUP_NAME = re.compile(r"career-search-backup-\d{8}T\d{12}Z-[0-9a-f]{32}\.sqlite3")


class BackupError(Exception):
    """A backup could not be created and validated."""


def _backup_uri(path: Path) -> str:
    """Build a read-only SQLite URI without losing special path characters."""
    return f"{path.resolve().as_uri()}?mode=ro"


def _owned_backups(directory: Path) -> list[Path]:
    """List files whose names match the backup utility's private naming scheme."""
    return sorted(
        (
            path
            for path in directory.iterdir()
            if BACKUP_NAME.fullmatch(path.name) and path.is_file() and not path.is_symlink()
        ),
        key=lambda path: path.name,
        reverse=True,
    )


def _prune_backups(directory: Path, keep: int, newest: Path) -> None:
    """Retain the new backup and the most recent older utility backups."""
    backups = _owned_backups(directory)
    retained = [newest]
    retained.extend(path for path in backups if path != newest)
    retained = retained[:keep]
    retained_set = set(retained)
    for path in backups:
        if path not in retained_set:
            path.unlink()


def _remove_temporary_files(path: Path) -> None:
    """Remove a failed temporary database and SQLite sidecar files."""
    for candidate in (path, Path(f"{path}-journal"), Path(f"{path}-wal"), Path(f"{path}-shm")):
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _check_integrity(path: Path) -> bool:
    """Return whether SQLite reports a clean integrity check for the backup."""
    check = sqlite3.connect(_backup_uri(path), uri=True, timeout=30)
    try:
        results = check.execute("PRAGMA integrity_check").fetchall()
    finally:
        check.close()
    return results == [("ok",)]


def create_backup(database: str | Path, directory: str | Path, keep: int = 7) -> Path:
    """Back up a live SQLite database and retain at most ``keep`` owned copies.

    The source opens in read-only mode, so a missing database is never created by
    SQLite. The backup API takes a consistent snapshot, including committed WAL
    pages. A temporary file is checked before it becomes visible under its final
    name, and old backups are pruned only after that atomic publication succeeds.
    """
    if isinstance(keep, bool) or not isinstance(keep, int) or keep < 1:
        raise ValueError("keep must be at least 1")

    source_path = Path(database)
    backup_directory = Path(directory)
    if not source_path.is_file():
        raise BackupError("source database is unavailable")

    source: sqlite3.Connection | None = None
    temporary_path: Path | None = None
    try:
        source = sqlite3.connect(_backup_uri(source_path), uri=True, timeout=30)

        backup_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(backup_directory, 0o700)

        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{BACKUP_PREFIX}", suffix=".tmp", dir=backup_directory
        )
        temporary_path = Path(temporary_name)
        try:
            os.fchmod(file_descriptor, 0o600)
        finally:
            os.close(file_descriptor)

        destination = sqlite3.connect(temporary_path, timeout=30)
        try:
            os.chmod(temporary_path, 0o600)
            source.backup(destination)
        finally:
            destination.close()

        source.close()
        source = None

        if not _check_integrity(temporary_path):
            raise BackupError("backup integrity check failed")

        os.chmod(temporary_path, 0o600)
        with temporary_path.open("rb") as backup_file:
            os.fsync(backup_file.fileno())

        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = backup_directory / (
            f"{BACKUP_PREFIX}{timestamp}-{uuid.uuid4().hex}{BACKUP_SUFFIX}"
        )
        os.replace(temporary_path, backup_path)
        temporary_path = None

        directory_descriptor = os.open(backup_directory, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)

        _prune_backups(backup_directory, keep, backup_path)
        return backup_path
    except BackupError:
        raise
    except (OSError, sqlite3.Error):
        # SQLite exception text can contain file paths. Keep CLI errors generic.
        raise BackupError("backup failed") from None
    finally:
        if source is not None:
            with suppress(sqlite3.Error):
                source.close()
        if temporary_path is not None:
            _remove_temporary_files(temporary_path)


def _positive_integer(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def main(argv: list[str] | None = None) -> int:
    """Run the backup command without printing stored job or profile contents."""
    parser = argparse.ArgumentParser(description="Create a private SQLite backup")
    parser.add_argument("--database", required=True, help="path to the SQLite database")
    parser.add_argument("--directory", required=True, help="directory for backup files")
    parser.add_argument(
        "--keep", type=_positive_integer, default=7, help="number of backups to retain"
    )
    arguments = parser.parse_args(argv)

    try:
        backup_path = create_backup(arguments.database, arguments.directory, arguments.keep)
    except BackupError:
        print(f"status=error backups=0 path={arguments.directory}", file=sys.stderr)
        return 1

    print(f"status=ok backups=1 path={backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
