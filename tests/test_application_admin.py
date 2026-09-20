"""The administrator route must require confirmation and validate imports first."""

import json
import sys

import pytest

from jobsearch_mcp.admin import main
from jobsearch_mcp.models import Job
from jobsearch_mcp.store import Store


def test_admin_mark_requires_confirmation_and_reads_back(tmp_path, monkeypatch, capsys):
    path = str(tmp_path / "jobs.db")
    store = Store(path)
    job = store.upsert(Job(title="Support Engineer", source_url="https://jobs.example/42"))
    args = [
        "career-admin",
        "--database",
        path,
        "mark-as-applied",
        "--job-id",
        job.id,
        "--evidence",
        "Trevor confirmed submission",
    ]
    monkeypatch.setattr(sys, "argv", args)
    with pytest.raises(SystemExit):
        main()
    assert store.get(job.id).submission is None
    monkeypatch.setattr(sys, "argv", [*args, "--confirmed"])
    main()
    result = json.loads(capsys.readouterr().out)
    assert result["persisted"] is True
    assert result["submission"]["submitted_at"] is None
    assert store.get(job.id).submission.evidence == "Trevor confirmed submission"


def test_invalid_import_batch_does_not_import_first_record(tmp_path, monkeypatch):
    path = str(tmp_path / "jobs.db")
    record = {
        "evidence": {
            "title": "Support Engineer",
            "source": "confirmed_library_record",
            "source_url": "https://jobs.example/42",
            "fetched_at": "2026-09-20T08:00:00Z",
            "retrieval_method": "DIRECT_CONNECTOR",
        },
        "submission": {
            "confirmed": True,
            "recorded_at": "2026-09-20T08:00:00Z",
            "evidence": "Explicit confirmation",
            "evidence_source": "confirmation_record",
        },
    }
    payload = tmp_path / "import.json"
    payload.write_text(json.dumps({"schema_version": 1, "records": [record, {"invalid": True}]}))
    monkeypatch.setattr(
        sys,
        "argv",
        ["career-admin", "--database", path, "import-applications", "--file", str(payload)],
    )
    with pytest.raises(ValueError):
        main()
    assert Store(path).list_jobs() == []


def test_import_retry_keeps_one_submission_event(tmp_path, monkeypatch, capsys):
    path = str(tmp_path / "jobs.db")
    record = {
        "evidence": {
            "title": "Support Engineer",
            "source": "confirmed_library_record",
            "source_url": "https://jobs.example/42",
            "fetched_at": "2026-09-20T08:00:00Z",
            "retrieval_method": "DIRECT_CONNECTOR",
        },
        "submission": {
            "confirmed": True,
            "recorded_at": "2026-09-20T08:00:00Z",
            "evidence": "Explicit confirmation",
            "evidence_source": "confirmation_record",
        },
    }
    payload = tmp_path / "import.json"
    payload.write_text(json.dumps({"schema_version": 1, "records": [record]}))
    monkeypatch.setattr(
        sys,
        "argv",
        ["career-admin", "--database", path, "import-applications", "--file", str(payload)],
    )
    main()
    first = json.loads(capsys.readouterr().out)
    main()
    second = json.loads(capsys.readouterr().out)
    assert first == second
    store = Store(path)
    job = store.list_jobs()[0]
    assert len(store.history(job.id)) == 2
    assert job.submission.confirmed is True
