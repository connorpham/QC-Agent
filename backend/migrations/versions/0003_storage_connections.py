"""storage connections; projects bind to a connection

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-01 20:00:00.000000

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_CONNECTION_NAME = "Local storage"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "storage_connections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("secret_enc", sa.Text(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "type IN ('localfs', 'sharepoint', 'gdrive')", name=op.f("ck_storage_connections_type")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_storage_connections_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_storage_connections")),
        sa.UniqueConstraint("name", name=op.f("uq_storage_connections_name")),
    )
    op.create_index(
        "uq_storage_connections_single_default",
        "storage_connections",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    # One default local connection rooted at LOCAL_STORAGE_ROOT ("."). Every existing project is
    # bound to it and keeps its root (the slug) and provisioned_at, so no file moves.
    connection_id = str(uuid.uuid4())
    op.execute(
        sa.text(
            "INSERT INTO storage_connections "
            "(id, type, name, config, secret_enc, is_default, is_active, created_by) "
            "VALUES (CAST(:id AS uuid), 'localfs', :name, CAST(:config AS jsonb), "
            "NULL, true, true, NULL)"
        ).bindparams(id=connection_id, name=DEFAULT_CONNECTION_NAME, config='{"root_path": "."}')
    )
    op.execute(
        sa.text(
            "UPDATE projects SET storage = (storage - 'type') "
            "|| jsonb_build_object('connection_id', CAST(:id AS text))"
        ).bindparams(id=connection_id)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "UPDATE projects SET storage = (storage - 'connection_id') "
        "|| jsonb_build_object('type', 'localfs')"
    )
    op.drop_index("uq_storage_connections_single_default", table_name="storage_connections")
    op.drop_table("storage_connections")
