from __future__ import annotations

import os
from contextlib import closing
from pathlib import Path
import sqlite3
import stat

from protocol import ReplayDetected


class TaskJournal:
    """Private, non-business operational replay/status ledger."""
    def __init__(self, path: Path):
        self.path = Path(path)
        parent = self.path.parent
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if parent.is_symlink() or parent.stat().st_uid != os.geteuid() or stat.S_IMODE(parent.stat().st_mode) & 0o077:
            raise ValueError("Unsafe bridge journal directory")
        if self.path.is_symlink():
            raise ValueError("Bridge journal may not be a symlink")
        if not self.path.exists():
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            os.close(fd)
        info = self.path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError("Unsafe bridge journal file")
        self.path.chmod(0o600)
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS tasks (task_id TEXT PRIMARY KEY, nonce TEXT UNIQUE NOT NULL, state TEXT NOT NULL, result_code TEXT, updated_at TEXT NOT NULL)")
            db.execute("COMMIT")
        self.path.chmod(0o600)

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def reserve(self, task_id: str, nonce: str, now: str) -> None:
        try:
            with closing(self._connect()) as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("INSERT INTO tasks(task_id, nonce, state, result_code, updated_at) VALUES(?, ?, 'RUNNING', NULL, ?)",
                           (task_id, nonce, now))
                db.execute("COMMIT")
        except sqlite3.IntegrityError as error:
            raise ReplayDetected("Task ID or replay nonce was already consumed") from error
        finally:
            self.path.chmod(0o600)

    def finish(self, task_id: str, state: str, result_code: str, now: str) -> None:
        if state not in {"SUCCEEDED", "BLOCKED", "FAILED"}:
            raise ValueError("Invalid terminal bridge state")
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute("UPDATE tasks SET state=?, result_code=?, updated_at=? WHERE task_id=? AND state='RUNNING'",
                                (state, result_code, now, task_id))
            if cursor.rowcount != 1:
                db.execute("ROLLBACK")
                raise ValueError("Bridge task journal state conflict")
            db.execute("COMMIT")
        self.path.chmod(0o600)

    def state(self, task_id: str):
        with closing(self._connect()) as db:
            row = db.execute("SELECT state, result_code FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        self.path.chmod(0o600)
        return row
