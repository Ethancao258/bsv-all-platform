"""Initial isolated/staging identity schema; never apply to existing CloudBase production.
Revision ID: bsv_identity_0001
Revises:
"""
from alembic import op
from domains.workforce.identity.models import Base, IsolatedBase, CodeAllocator
from sqlalchemy.orm import Session

revision = "bsv_identity_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind=op.get_bind()
    Base.metadata.create_all(bind=bind)
    # Test auth account table only; excluded from production candidate schema.
    IsolatedBase.metadata.create_all(bind=bind)
    with Session(bind=bind) as session:
        if not session.get(CodeAllocator,1):
            session.add(CodeAllocator(id=1,next_index=0))
        session.flush()


def downgrade():
    # Only isolated disposable test environments. This drops all identity data.
    IsolatedBase.metadata.drop_all(bind=op.get_bind())
    Base.metadata.drop_all(bind=op.get_bind())
