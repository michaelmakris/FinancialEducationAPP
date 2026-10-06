"""add market data: OHLCV columns, instrument source/LEI, ESEF facts, indicators, crypto snapshots

Revision ID: e5a1c3d9b7f2
Revises: c7f3a9d2e1b4
Create Date: 2026-10-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5a1c3d9b7f2'
down_revision: Union[str, None] = 'c7f3a9d2e1b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('instruments') as b:
        b.add_column(sa.Column('data_source', sa.String(length=20), nullable=False, server_default='simulated'))
        b.add_column(sa.Column('country', sa.String(length=2), nullable=False, server_default=''))
        b.add_column(sa.Column('lei', sa.String(length=20), nullable=True))
        b.add_column(sa.Column('vendor_symbol', sa.String(length=40), nullable=True))
    op.create_index(op.f('ix_instruments_data_source'), 'instruments', ['data_source'], unique=False)
    op.create_index(op.f('ix_instruments_lei'), 'instruments', ['lei'], unique=False)

    with op.batch_alter_table('price_bars') as b:
        for col in ('open', 'high', 'low', 'volume', 'adj_close'):
            b.add_column(sa.Column(col, sa.Float(), nullable=True))

    op.create_table('reported_facts',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('instrument_id', sa.String(length=36), nullable=False),
    sa.Column('concept', sa.String(length=200), nullable=False),
    sa.Column('period_start', sa.Date(), nullable=True),
    sa.Column('period_end', sa.Date(), nullable=False),
    sa.Column('value', sa.Float(), nullable=False),
    sa.Column('unit', sa.String(length=40), nullable=False),
    sa.Column('filing_id', sa.String(length=80), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('instrument_id', 'concept', 'period_start', 'period_end', name='uq_reported_fact')
    )
    op.create_index(op.f('ix_reported_facts_instrument_id'), 'reported_facts', ['instrument_id'], unique=False)
    op.create_index(op.f('ix_reported_facts_concept'), 'reported_facts', ['concept'], unique=False)
    op.create_index(op.f('ix_reported_facts_period_end'), 'reported_facts', ['period_end'], unique=False)
    op.create_index(op.f('ix_reported_facts_filing_id'), 'reported_facts', ['filing_id'], unique=False)

    op.create_table('indicators',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('geo', sa.String(length=20), nullable=False),
    sa.Column('unit', sa.String(length=30), nullable=False),
    sa.Column('frequency', sa.String(length=1), nullable=False),
    sa.Column('source', sa.String(length=40), nullable=False),
    sa.Column('source_key', sa.String(length=300), nullable=False),
    sa.Column('category', sa.String(length=30), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )

    op.create_table('indicator_observations',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('indicator_id', sa.String(length=40), nullable=False),
    sa.Column('period_date', sa.Date(), nullable=False),
    sa.Column('value', sa.Float(), nullable=False),
    sa.Column('fetched_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['indicator_id'], ['indicators.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('indicator_id', 'period_date', name='uq_indicator_observation')
    )
    op.create_index(op.f('ix_indicator_observations_indicator_id'), 'indicator_observations', ['indicator_id'], unique=False)
    op.create_index(op.f('ix_indicator_observations_period_date'), 'indicator_observations', ['period_date'], unique=False)

    op.create_table('indicator_snapshots',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('indicator_id', sa.String(length=40), nullable=False),
    sa.Column('as_of_date', sa.Date(), nullable=False),
    sa.Column('obs_date', sa.Date(), nullable=False),
    sa.Column('value', sa.Float(), nullable=False),
    sa.Column('value_90d_prior', sa.Float(), nullable=True),
    sa.Column('direction_90d', sa.String(length=10), nullable=False),
    sa.Column('value_1y', sa.Float(), nullable=True),
    sa.Column('value_eu', sa.Float(), nullable=True),
    sa.Column('staleness_d', sa.Integer(), nullable=False),
    sa.Column('payload_eligible', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['indicator_id'], ['indicators.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('indicator_id', 'as_of_date', name='uq_indicator_snapshot')
    )
    op.create_index(op.f('ix_indicator_snapshots_indicator_id'), 'indicator_snapshots', ['indicator_id'], unique=False)
    op.create_index(op.f('ix_indicator_snapshots_as_of_date'), 'indicator_snapshots', ['as_of_date'], unique=False)

    op.create_table('crypto_market_snapshots',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('instrument_id', sa.String(length=36), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('currency', sa.String(length=10), nullable=False),
    sa.Column('price', sa.Float(), nullable=True),
    sa.Column('market_cap', sa.Float(), nullable=True),
    sa.Column('volume_24h', sa.Float(), nullable=True),
    sa.Column('circulating_supply', sa.Float(), nullable=True),
    sa.Column('market_cap_rank', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('instrument_id', 'date', name='uq_crypto_snapshot')
    )
    op.create_index(op.f('ix_crypto_market_snapshots_instrument_id'), 'crypto_market_snapshots', ['instrument_id'], unique=False)
    op.create_index(op.f('ix_crypto_market_snapshots_date'), 'crypto_market_snapshots', ['date'], unique=False)


def downgrade() -> None:
    op.drop_table('crypto_market_snapshots')
    op.drop_table('indicator_snapshots')
    op.drop_table('indicator_observations')
    op.drop_table('indicators')
    op.drop_table('reported_facts')
    with op.batch_alter_table('price_bars') as b:
        for col in ('adj_close', 'volume', 'low', 'high', 'open'):
            b.drop_column(col)
    op.drop_index(op.f('ix_instruments_lei'), table_name='instruments')
    op.drop_index(op.f('ix_instruments_data_source'), table_name='instruments')
    with op.batch_alter_table('instruments') as b:
        for col in ('vendor_symbol', 'lei', 'country', 'data_source'):
            b.drop_column(col)
