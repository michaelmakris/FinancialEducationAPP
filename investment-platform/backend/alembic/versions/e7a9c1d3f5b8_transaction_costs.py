"""transaction costs: portfolio cost profile and fees per trade

Revision ID: e7a9c1d3f5b8
Revises: d4f6b8c0e2a5
Create Date: 2026-10-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e7a9c1d3f5b8'
down_revision: Union[str, None] = 'd4f6b8c0e2a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('portfolios', sa.Column('cost_profile', sa.String(length=10), nullable=True))
    op.add_column('transactions', sa.Column('fees', sa.Float(), server_default='0', nullable=False))


def downgrade() -> None:
    op.drop_column('transactions', 'fees')
    op.drop_column('portfolios', 'cost_profile')
