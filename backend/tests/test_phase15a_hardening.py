import asyncio
import os
import subprocess
import time
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from common.models import InboxItem
from worker.main import handle_memory_compact, utc_now


class _FakeResult:
    def __init__(self, items=None):
        self._items = items or []

    def scalars(self):
        return self

    def all(self):
        return self._items


class _FakeDeleteResult:
    rowcount = 1


def _session_factory(fake_db):
    @asynccontextmanager
    async def _ctx():
        yield fake_db

    return lambda: _ctx()


def test_memory_compact_keeps_task_and_draft_references():
    async def _run():
        now = utc_now()
        eligible = [
            InboxItem(id="inb_task", user_id="usr_dev", chat_id="c1", source="telegram", message_raw="a", message_norm="a", received_at=now - timedelta(days=40)),
            InboxItem(id="inb_draft", user_id="usr_dev", chat_id="c1", source="telegram", message_raw="b", message_norm="b", received_at=now - timedelta(days=40)),
            InboxItem(id="inb_delete", user_id="usr_dev", chat_id="c1", source="telegram", message_raw="c", message_norm="c", received_at=now - timedelta(days=40)),
        ]

        fake_db = AsyncMock()
        fake_db.execute = AsyncMock(
            side_effect=[
                _FakeResult(items=eligible),             # eligible inbox rows
                _FakeResult(items=["inb_task"]),         # task references
                _FakeResult(items=["inb_draft"]),        # active draft references
                _FakeDeleteResult(),                     # delete non-referenced
            ]
        )
        fake_db.add = MagicMock()
        fake_db.commit = AsyncMock()

        with patch("worker.main.AsyncSessionLocal", _session_factory(fake_db)):
            await handle_memory_compact("job_compact", {"user_id": "usr_dev"})

        assert fake_db.execute.await_count == 4
        assert fake_db.commit.await_count == 1
        added_event = fake_db.add.call_args.args[0]
        assert added_event.event_type == "memory_compaction_completed"
        assert added_event.payload_json["eligible_old_rows"] == 3
        assert added_event.payload_json["skipped_referenced_rows"] == 2
        assert added_event.payload_json["deleted_rows"] == 1

    asyncio.run(_run())


def test_backup_script_prunes_expired_files_when_within_limit(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "ops" / "backup_db.sh"
    db_file = tmp_path / "app.db"
    db_file.write_text("sqlite-db")
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    old_file = backup_dir / "old_backup.sql"
    old_file.write_text("old")
    stale = time.time() - (20 * 24 * 60 * 60)
    os.utime(old_file, (stale, stale))

    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_file}"
    env["BACKUP_DIR"] = str(backup_dir)
    env["BACKUP_RETENTION_DAYS"] = "14"
    env["BACKUP_DELETE_MAX_FILES"] = "10"

    result = subprocess.run(
        ["bash", str(script)],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "Created SQLite backup:" in result.stdout
    assert not old_file.exists()


def test_backup_script_skips_prune_when_candidate_count_exceeds_limit(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "ops" / "backup_db.sh"
    db_file = tmp_path / "app.db"
    db_file.write_text("sqlite-db")
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    old_a = backup_dir / "old_a.sql"
    old_b = backup_dir / "old_b.sql"
    old_a.write_text("a")
    old_b.write_text("b")
    stale = time.time() - (20 * 24 * 60 * 60)
    os.utime(old_a, (stale, stale))
    os.utime(old_b, (stale, stale))

    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_file}"
    env["BACKUP_DIR"] = str(backup_dir)
    env["BACKUP_RETENTION_DAYS"] = "14"
    env["BACKUP_DELETE_MAX_FILES"] = "1"

    result = subprocess.run(
        ["bash", str(script)],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "Skipping retention prune" in result.stderr
    assert old_a.exists()
    assert old_b.exists()

