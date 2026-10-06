"""personal access keys for AI assistants (MCP)

Revision ID: c3d4e5f6a7b8
Revises: b7c8d9e0f1a2
Create Date: 2026-10-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b7c8d9e0f1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('auth_access_keys',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('customer_id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('prefix', sa.String(length=16), nullable=False),
    sa.Column('scopes', sa.String(length=200), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('last_used_at', sa.DateTime(), nullable=True),
    sa.Column('revoked_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['customer_id'], ['auth_customers.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_auth_access_keys_customer_id'), 'auth_access_keys', ['customer_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_auth_access_keys_customer_id'), table_name='auth_access_keys')
    op.drop_table('auth_access_keys')
