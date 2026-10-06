"""add chat_interactions table

Revision ID: c7f3a9d2e1b4
Revises: 1b208b07d333
Create Date: 2026-09-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7f3a9d2e1b4'
down_revision: Union[str, None] = '1b208b07d333'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('chat_interactions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('user_message', sa.Text(), nullable=False),
    sa.Column('assistant_reply', sa.Text(), nullable=False),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('agents_used', sa.String(length=200), nullable=False),
    sa.Column('actions_json', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('detail', sa.String(length=500), nullable=False),
    sa.Column('latency_ms', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_chat_interactions_created_at'), 'chat_interactions', ['created_at'], unique=False)
    op.create_index(op.f('ix_chat_interactions_status'), 'chat_interactions', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_chat_interactions_status'), table_name='chat_interactions')
    op.drop_index(op.f('ix_chat_interactions_created_at'), table_name='chat_interactions')
    op.drop_table('chat_interactions')
