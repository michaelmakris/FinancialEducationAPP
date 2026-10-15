"""chat_interactions.tokens_used for the per-customer daily AI budget

Revision ID: d4f6b8c0e2a5
Revises: c3e5a7b9d1f4
Create Date: 2026-10-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd4f6b8c0e2a5'
down_revision: Union[str, None] = 'c3e5a7b9d1f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('chat_interactions', sa.Column('tokens_used', sa.Integer(), server_default='0', nullable=False))


def downgrade() -> None:
    op.drop_column('chat_interactions', 'tokens_used')
