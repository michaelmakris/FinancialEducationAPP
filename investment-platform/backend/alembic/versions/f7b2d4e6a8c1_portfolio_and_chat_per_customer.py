"""portfolios and chat interactions belong to a customer (the BFF token subject)

Revision ID: f7b2d4e6a8c1
Revises: e5a1c3d9b7f2
Create Date: 2026-10-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7b2d4e6a8c1'
down_revision: Union[str, None] = 'e5a1c3d9b7f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing rows keep customer_id NULL: the old single shared demo portfolio is
    # never served to anyone once login exists (each customer gets a fresh one).
    with op.batch_alter_table('portfolios') as b:
        b.add_column(sa.Column('customer_id', sa.String(length=64), nullable=True))
    op.create_index(op.f('ix_portfolios_customer_id'), 'portfolios', ['customer_id'], unique=True)
    with op.batch_alter_table('chat_interactions') as b:
        b.add_column(sa.Column('customer_id', sa.String(length=64), nullable=True))
    op.create_index(op.f('ix_chat_interactions_customer_id'), 'chat_interactions', ['customer_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_chat_interactions_customer_id'), table_name='chat_interactions')
    with op.batch_alter_table('chat_interactions') as b:
        b.drop_column('customer_id')
    op.drop_index(op.f('ix_portfolios_customer_id'), table_name='portfolios')
    with op.batch_alter_table('portfolios') as b:
        b.drop_column('customer_id')
