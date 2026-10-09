"""risk assessments and educational proposals (proposals/)

Revision ID: b2d4f6a8c0e1
Revises: a9c1e3f5b7d2
Create Date: 2026-10-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b2d4f6a8c0e1'
down_revision: Union[str, None] = 'a9c1e3f5b7d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('risk_assessments',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('customer_id', sa.String(length=64), nullable=False),
    sa.Column('questionnaire_version', sa.Integer(), nullable=False),
    sa.Column('answers_json', sa.Text(), nullable=False),
    sa.Column('result_json', sa.Text(), nullable=False),
    sa.Column('profile', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_risk_assessments_customer_id'), 'risk_assessments', ['customer_id'], unique=False)
    op.create_index(op.f('ix_risk_assessments_created_at'), 'risk_assessments', ['created_at'], unique=False)

    op.create_table('proposals',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('customer_id', sa.String(length=64), nullable=False),
    sa.Column('risk_assessment_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('engine_version', sa.String(length=20), nullable=False),
    sa.Column('proposal_json', sa.Text(), nullable=False),
    sa.Column('narrative', sa.Text(), nullable=False),
    sa.Column('narrative_source', sa.String(length=200), nullable=False),
    sa.ForeignKeyConstraint(['risk_assessment_id'], ['risk_assessments.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_proposals_customer_id'), 'proposals', ['customer_id'], unique=False)
    op.create_index(op.f('ix_proposals_created_at'), 'proposals', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_table('proposals')
    op.drop_table('risk_assessments')
