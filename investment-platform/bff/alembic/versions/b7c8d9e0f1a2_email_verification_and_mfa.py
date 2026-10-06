"""email verification, password reset and MFA: tokens, recovery codes, customer MFA columns

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-10-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b7c8d9e0f1a2'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('auth_customers') as b:
        b.add_column(sa.Column('email_verified_at', sa.DateTime(), nullable=True))
        b.add_column(sa.Column('mfa_secret_enc', sa.Text(), nullable=True))
        b.add_column(sa.Column('mfa_pending_secret_enc', sa.Text(), nullable=True))
        b.add_column(sa.Column('mfa_enabled_at', sa.DateTime(), nullable=True))
        b.add_column(sa.Column('mfa_last_step', sa.Integer(), nullable=True))

    op.create_table('auth_tokens',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('customer_id', sa.String(length=36), nullable=False),
    sa.Column('purpose', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('used_at', sa.DateTime(), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['auth_customers.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_auth_tokens_customer_id'), 'auth_tokens', ['customer_id'], unique=False)

    op.create_table('auth_recovery_codes',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('customer_id', sa.String(length=36), nullable=False),
    sa.Column('code_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('used_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['customer_id'], ['auth_customers.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_auth_recovery_codes_customer_id'), 'auth_recovery_codes', ['customer_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_auth_recovery_codes_customer_id'), table_name='auth_recovery_codes')
    op.drop_table('auth_recovery_codes')
    op.drop_index(op.f('ix_auth_tokens_customer_id'), table_name='auth_tokens')
    op.drop_table('auth_tokens')
    with op.batch_alter_table('auth_customers') as b:
        for col in ('mfa_last_step', 'mfa_enabled_at', 'mfa_pending_secret_enc', 'mfa_secret_enc', 'email_verified_at'):
            b.drop_column(col)
