"""recovery allocations (recorded pro-rata splits of money in accounts shared by several disputes)

Revision ID: f3b9c2d17a45
Revises: e8a3f1c06d27
Create Date: 2026-10-18 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f3b9c2d17a45'
down_revision: Union[str, Sequence[str], None] = 'e8a3f1c06d27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'recovery_allocations',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('account_id', sa.String(length=32), nullable=False),
        sa.Column('method', sa.String(length=32), nullable=False),
        sa.Column('basis', sa.String(length=16), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('available_minor', sa.BigInteger(), nullable=False),
        sa.Column('allocations', sa.JSON(), nullable=False),
        sa.Column('details', sa.JSON(), nullable=False),
        sa.Column('note', sa.Text(), nullable=False),  # encrypted
        sa.Column('recorded_by', sa.String(length=64), nullable=False),
        sa.Column('recorded_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_recovery_allocations_account_id'), 'recovery_allocations', ['account_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_recovery_allocations_account_id'), table_name='recovery_allocations')
    op.drop_table('recovery_allocations')
