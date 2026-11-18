"""Create isolated schema, never touch a production master database."""
import argparse
from sqlalchemy.engine import make_url
from .config import load_settings
from .database import SourceRouter
from domains.workforce.identity.models import Base, IsolatedBase, CodeAllocator


def isolated_guard(settings):
    if settings.env == "production":
        raise RuntimeError("Production migration is locked; requires existing CloudBase migration manager G0/G1")
    address = make_url(settings.db_a_url)
    if address.get_backend_name() == "postgresql":
        if address.host not in {"127.0.0.1","::1","localhost","pg"} or not (
                address.database or "").startswith(("bsv_identity_isolated","bsv_identity_staging")):
            raise RuntimeError("Identity migration requires a dedicated isolated PostgreSQL database")
    elif address.get_backend_name() != "sqlite" or settings.env != "isolated":
        raise RuntimeError("Only isolated SQLite or dedicated PostgreSQL is allowed")


def init_db():
    s = load_settings();isolated_guard(s)
    db = SourceRouter(s)
    Base.metadata.create_all(db.a)
    if s.env == "isolated":
        IsolatedBase.metadata.create_all(db.a)
    with db.session(write=True) as session:
        if not session.get(CodeAllocator, 1):
            session.add(CodeAllocator(id=1, next_index=0))
    print("ISOLATED_SCHEMA_OK", s.env, db.a.dialect.name)


def main():
    p=argparse.ArgumentParser(description="BSV identity isolated database setup")
    p.add_argument("command",choices=["init-db","check-ready","schema-sql"])
    args=p.parse_args()
    if args.command == "init-db":
        init_db()
    elif args.command == "check-ready":
        db=SourceRouter()
        with db.session() as s:
            if not s.get(CodeAllocator,1):raise RuntimeError("Allocator missing")
        print("READINESS_OK: database A")
    else:
        from sqlalchemy.schema import CreateTable, CreateIndex
        from sqlalchemy.dialects import postgresql
        for table in Base.metadata.sorted_tables:
            print(str(CreateTable(table).compile(dialect=postgresql.dialect()))+";\n")
            for index in table.indexes:
                print(str(CreateIndex(index).compile(dialect=postgresql.dialect()))+";\n")


if __name__ == "__main__": main()
