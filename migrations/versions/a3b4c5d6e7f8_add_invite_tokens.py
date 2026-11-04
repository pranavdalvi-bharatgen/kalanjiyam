"""Add invite_tokens table.

Revision ID: a3b4c5d6e7f8
Revises: c7d8e9f0a1b2
Create Date: 2026-11-04
"""

import sqlalchemy as sa
from alembic import op

revision = "a3b4c5d6e7f8"
down_revision = "c7d8e9f0a1b2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "invite_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("uses_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["groups.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_invite_tokens_token_hash"),
    )
    op.create_index("ix_invite_tokens_org_id", "invite_tokens", ["org_id"])
    op.create_index(
        "ix_invite_tokens_created_by_user_id", "invite_tokens", ["created_by_user_id"]
    )
    op.create_index("ix_invite_tokens_token_hash", "invite_tokens", ["token_hash"])


def downgrade():
    op.drop_index("ix_invite_tokens_token_hash", table_name="invite_tokens")
    op.drop_index("ix_invite_tokens_created_by_user_id", table_name="invite_tokens")
    op.drop_index("ix_invite_tokens_org_id", table_name="invite_tokens")
    op.drop_table("invite_tokens")
