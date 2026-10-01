"""ingestion: project storage binding, consent, uploads, documents

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-01 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "projects", sa.Column("storage", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column(
        "projects",
        sa.Column("llm_consent", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    # Existing projects are bound to local storage under their slug; their workspace is
    # provisioned lazily on the first publish (ensure_workspace is idempotent).
    op.execute("UPDATE projects SET storage = jsonb_build_object('type', 'localfs', 'root', slug)")
    op.alter_column("projects", "storage", nullable=False)

    op.create_table(
        "uploads",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("uploaded_by", sa.UUID(), nullable=False),
        sa.Column("repo_ref", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_uploads_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"], ["users.id"], name=op.f("fk_uploads_uploaded_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_uploads")),
    )
    op.create_index(op.f("ix_uploads_project_id"), "uploads", ["project_id"], unique=False)
    op.create_index(op.f("ix_uploads_uploaded_by"), "uploads", ["uploaded_by"], unique=False)

    op.create_table(
        "documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("folder_id", sa.String(length=40), nullable=False),
        sa.Column("doc_type", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("visibility", sa.String(length=8), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("is_stub", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
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
            "(is_stub AND slug = '') OR (NOT is_stub AND slug <> '')",
            name=op.f("ck_documents_stub_slug"),
        ),
        sa.CheckConstraint(
            "visibility IN ('internal', 'shared')", name=op.f("ck_documents_visibility")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_documents_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_documents_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint(
            "project_id", "doc_type", "slug", name=op.f("uq_documents_project_type_slug")
        ),
    )
    op.create_index(op.f("ix_documents_project_id"), "documents", ["project_id"], unique=False)

    op.create_table(
        "upload_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("upload_id", sa.UUID(), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("ext", sa.String(length=8), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("staging_path", sa.String(length=500), nullable=False),
        sa.Column("selected_doc_type", sa.String(length=80), nullable=False),
        sa.Column("final_doc_type", sa.String(length=80), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("intent", sa.String(length=8), nullable=False),
        sa.Column("target_document_id", sa.UUID(), nullable=True),
        sa.Column("visibility", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("type_check", sa.String(length=24), nullable=True),
        sa.Column("check_explanation", sa.Text(), nullable=True),
        sa.Column("suggested_doc_type", sa.String(length=80), nullable=True),
        sa.Column("version_hint_document_id", sa.UUID(), nullable=True),
        sa.Column("conversion_meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
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
        sa.CheckConstraint("intent IN ('new', 'version')", name=op.f("ck_upload_items_intent")),
        sa.CheckConstraint(
            "status IN ('uploaded', 'converting', 'checking', 'needs_confirmation', "
            "'publishing', 'published', 'failed')",
            name=op.f("ck_upload_items_status"),
        ),
        sa.CheckConstraint(
            "type_check IS NULL OR type_check IN ('match', 'mismatch_kept', "
            "'mismatch_changed', 'skipped')",
            name=op.f("ck_upload_items_type_check"),
        ),
        sa.CheckConstraint(
            "visibility IN ('internal', 'shared')", name=op.f("ck_upload_items_visibility")
        ),
        sa.ForeignKeyConstraint(
            ["target_document_id"],
            ["documents.id"],
            name=op.f("fk_upload_items_target_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["upload_id"],
            ["uploads.id"],
            name=op.f("fk_upload_items_upload_id_uploads"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["version_hint_document_id"],
            ["documents.id"],
            name=op.f("fk_upload_items_version_hint_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_upload_items")),
    )
    op.create_index(op.f("ix_upload_items_status"), "upload_items", ["status"], unique=False)
    op.create_index(op.f("ix_upload_items_upload_id"), "upload_items", ["upload_id"], unique=False)

    op.create_table(
        "document_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("original_path", sa.String(length=500), nullable=True),
        sa.Column("original_storage_version", sa.String(length=100), nullable=True),
        sa.Column("markdown_path", sa.String(length=500), nullable=False),
        sa.Column("markdown_storage_version", sa.String(length=100), nullable=False),
        sa.Column("markdown_text", sa.Text(), nullable=False),
        sa.Column("uploaded_by", sa.UUID(), nullable=False),
        sa.Column("upload_item_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_versions_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["upload_item_id"],
            ["upload_items.id"],
            name=op.f("fk_document_versions_upload_item_id_upload_items"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"], ["users.id"], name=op.f("fk_document_versions_uploaded_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_versions")),
        sa.UniqueConstraint(
            "document_id", "version", name=op.f("uq_document_versions_document_version")
        ),
        sa.UniqueConstraint("upload_item_id", name=op.f("uq_document_versions_upload_item_id")),
    )
    op.create_index(
        op.f("ix_document_versions_document_id"), "document_versions", ["document_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_document_versions_document_id"), table_name="document_versions")
    op.drop_table("document_versions")
    op.drop_index(op.f("ix_upload_items_upload_id"), table_name="upload_items")
    op.drop_index(op.f("ix_upload_items_status"), table_name="upload_items")
    op.drop_table("upload_items")
    op.drop_index(op.f("ix_documents_project_id"), table_name="documents")
    op.drop_table("documents")
    op.drop_index(op.f("ix_uploads_uploaded_by"), table_name="uploads")
    op.drop_index(op.f("ix_uploads_project_id"), table_name="uploads")
    op.drop_table("uploads")
    op.drop_column("projects", "llm_consent")
    op.drop_column("projects", "storage")
