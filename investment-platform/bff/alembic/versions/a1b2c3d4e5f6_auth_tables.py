"""auth tables: customers, sessions, audit events

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-10-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('auth_customers',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('full_name', sa.String(length=200), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('email_verified', sa.Boolean(), nullable=False),
    sa.Column('failed_login_count', sa.Integer(), nullable=False),
    sa.Column('locked_until', sa.DateTime(), nullable=True),
    sa.Column('last_login_at', sa.DateTime(), nullable=True),
    sa.Column('password_changed_at', sa.DateTime(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_auth_customers_email'), 'auth_customers', ['email'], unique=True)

    op.create_table('auth_sessions',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('customer_id', sa.String(length=36), nullable=False),
    sa.Column('csrf_token', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('revoked_at', sa.DateTime(), nullable=True),
    sa.Column('ip', sa.String(length=64), nullable=False),
    sa.Column('user_agent', sa.String(length=300), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['auth_customers.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_auth_sessions_customer_id'), 'auth_sessions', ['customer_id'], unique=False)

    op.create_table('auth_events',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('at', sa.DateTime(), nullable=False),
    sa.Column('customer_id', sa.String(length=36), nullable=True),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('event', sa.String(length=40), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=False),
    sa.Column('user_agent', sa.String(length=300), nullable=False),
    sa.Column('detail', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_auth_events_at'), 'auth_events', ['at'], unique=False)
    op.create_index(op.f('ix_auth_events_customer_id'), 'auth_events', ['customer_id'], unique=False)
    op.create_index(op.f('ix_auth_events_event'), 'auth_events', ['event'], unique=False)


def downgrade() -> None:
    op.drop_table('auth_events')
    op.drop_table('auth_sessions')
    op.drop_index(op.f('ix_auth_customers_email'), table_name='auth_customers')
    op.drop_table('auth_customers')
