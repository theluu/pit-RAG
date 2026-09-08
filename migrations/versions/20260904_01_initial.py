"""Initial persisted legal RAG schema."""
from alembic import op

revision = "20260904_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Runtime bootstrap remains idempotent for SQLite tests; production runs this
    # migration before the API starts.
    from apps.api.database import Base
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    from apps.api.database import Base
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
