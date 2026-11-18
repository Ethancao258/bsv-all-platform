"""Database A is authoritative; B is optional READ-ONLY, never used for authorization."""
from contextlib import contextmanager
from pathlib import Path
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from .config import load_settings


def make_engine(url):
    if url.startswith("sqlite"):
        if "///" in url and not url.endswith(":memory:"):
            path = url.split("///", 1)[1]
            if path and path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 35}, pool_pre_ping=True)
        @event.listens_for(engine, "connect")
        def pragmas(conn, _record):
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=35000")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()
    else:
        engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=15,
                               pool_recycle=1800, connect_args={"connect_timeout": 5})
    return engine


class SourceRouter:
    def __init__(self, settings=None, override_url=None):
        self.settings = settings or load_settings()
        self.a = make_engine(override_url or self.settings.db_a_url)
        self._factory = sessionmaker(bind=self.a, expire_on_commit=False)
        self.b = make_engine(self.settings.db_b_url) if self.settings.db_b_url else None

    @contextmanager
    def session(self, *, write=False, purpose="authorization"):
        """Read and write to A; SQLite's BEGIN IMMEDIATE emulates PG allocator locking in tests.

        Never use B or LOCAL for authentication, authorization, audit or grants.
        """
        if self.settings.source_config["bindings"].get(purpose, "A") != "A":
            raise RuntimeError("Unknown authoritative purpose; fail closed")
        db = self._factory()
        try:
            if write and db.bind.dialect.name == "sqlite":
                db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def ping(self):
        with self.a.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True

    def non_sensitive_reference_connection(self):
        """B is not a fallback for sensitive identities or permissions."""
        if not self.b:
            raise RuntimeError("Database B optional reference replica not configured")
        if self.b.dialect.name != "postgresql":
            raise RuntimeError("Database B requires a PostgreSQL read-only replica")
        conn = self.b.connect()
        try:
            conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            return conn
        except Exception:
            conn.close()
            raise
