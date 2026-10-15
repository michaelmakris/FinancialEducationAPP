"""instrument market + trade details for the real-price practice portfolio

Revision ID: c3e5a7b9d1f4
Revises: b2d4f6a8c0e1
Create Date: 2026-10-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c3e5a7b9d1f4'
down_revision: Union[str, None] = 'b2d4f6a8c0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('instruments', sa.Column('market', sa.String(length=10), server_default='', nullable=False))
    op.create_index(op.f('ix_instruments_market'), 'instruments', ['market'], unique=False)
    # already-loaded real instruments: Athens stocks, Binance coins, benchmarks
    op.execute("UPDATE instruments SET market = 'athens' WHERE data_source = 'yahoo' AND ticker LIKE '%.AT' AND asset_type = 'equity'")
    op.execute("UPDATE instruments SET market = 'crypto' WHERE data_source = 'binance'")
    op.execute("UPDATE instruments SET market = 'index' WHERE data_source = 'yahoo' AND market = ''")

    op.add_column('transactions', sa.Column('price_local', sa.Float(), nullable=True))
    op.add_column('transactions', sa.Column('currency', sa.String(length=10), server_default='EUR', nullable=False))
    op.add_column('transactions', sa.Column('fx_rate', sa.Float(), server_default='1', nullable=False))
    op.add_column('transactions', sa.Column('realized_pnl', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('transactions', 'realized_pnl')
    op.drop_column('transactions', 'fx_rate')
    op.drop_column('transactions', 'currency')
    op.drop_column('transactions', 'price_local')
    op.drop_index(op.f('ix_instruments_market'), table_name='instruments')
    op.drop_column('instruments', 'market')
