"""Add isolated Academy, shift and terminal facts. Never run on production."""
from alembic import op

from domains.learning.academy_models import AcademyBase

revision = "bsv_academy_0002"
down_revision = "bsv_identity_0001"
branch_labels = None
depends_on = None


def upgrade():
    AcademyBase.metadata.create_all(bind=op.get_bind())


def downgrade():
    # This is used only for a disposable migration rehearsal. Operational
    # application rollback retains the additive tables and all their history.
    AcademyBase.metadata.drop_all(bind=op.get_bind())
