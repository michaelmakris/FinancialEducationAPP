"""model registry and served predictions (forecasting/)

Revision ID: a9c1e3f5b7d2
Revises: f7b2d4e6a8c1
Create Date: 2026-10-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a9c1e3f5b7d2'
down_revision: Union[str, None] = 'f7b2d4e6a8c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('model_versions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('model_name', sa.String(length=40), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('algorithm', sa.String(length=80), nullable=False),
    sa.Column('trained_at', sa.DateTime(), nullable=False),
    sa.Column('data_start', sa.Date(), nullable=True),
    sa.Column('data_end', sa.Date(), nullable=True),
    sa.Column('metrics_json', sa.Text(), nullable=False),
    sa.Column('baseline_json', sa.Text(), nullable=False),
    sa.Column('params_json', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('status_reason', sa.String(length=500), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('model_name', 'version', name='uq_model_version')
    )
    op.create_index(op.f('ix_model_versions_model_name'), 'model_versions', ['model_name'], unique=False)
    op.create_index(op.f('ix_model_versions_status'), 'model_versions', ['status'], unique=False)

    op.create_table('model_predictions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('model_version_id', sa.Integer(), nullable=False),
    sa.Column('model_name', sa.String(length=40), nullable=False),
    sa.Column('subject', sa.String(length=40), nullable=False),
    sa.Column('target', sa.String(length=40), nullable=False),
    sa.Column('as_of_date', sa.Date(), nullable=False),
    sa.Column('horizon_days', sa.Integer(), nullable=False),
    sa.Column('value', sa.Float(), nullable=False),
    sa.Column('details_json', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['model_version_id'], ['model_versions.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('model_name', 'subject', 'target', 'as_of_date', name='uq_model_prediction')
    )
    op.create_index(op.f('ix_model_predictions_model_version_id'), 'model_predictions', ['model_version_id'], unique=False)
    op.create_index(op.f('ix_model_predictions_model_name'), 'model_predictions', ['model_name'], unique=False)
    op.create_index(op.f('ix_model_predictions_subject'), 'model_predictions', ['subject'], unique=False)
    op.create_index(op.f('ix_model_predictions_as_of_date'), 'model_predictions', ['as_of_date'], unique=False)


def downgrade() -> None:
    op.drop_table('model_predictions')
    op.drop_table('model_versions')
