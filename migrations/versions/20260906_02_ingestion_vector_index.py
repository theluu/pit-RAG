"""Add asynchronous PDF ingestion and versioned vector indexes."""

from alembic import op

revision = "20260906_02"
down_revision = "20260904_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from apps.api.database import Base, vector_ddl

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    if bind.dialect.name == "postgresql":
        for statement in vector_ddl():
            op.execute(statement)


def downgrade() -> None:
    for table in ("provision_index_entries", "index_versions", "document_pages",
                  "ingestion_jobs", "document_files"):
        op.drop_table(table)
