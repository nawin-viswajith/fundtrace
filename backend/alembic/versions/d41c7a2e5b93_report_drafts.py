"""report drafts (unsaved report edits made in the UI or through the case assistant)

Revision ID: d41c7a2e5b93
Revises: b7e1d2c4a9f0
Create Date: 2026-10-18 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd41c7a2e5b93'
down_revision: Union[str, Sequence[str], None] = 'b7e1d2c4a9f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'report_drafts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('report_id', sa.String(length=32), nullable=False),
        sa.Column('case_id', sa.String(length=32), nullable=False),
        sa.Column('sections', sa.JSON(), nullable=False),
        sa.Column('changes', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('saved_report_id', sa.String(length=32), nullable=True),
        sa.Column('created_by', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['case_id'], ['dispute_cases.id']),
        sa.ForeignKeyConstraint(['report_id'], ['reports.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_report_drafts_case_id'), 'report_drafts', ['case_id'], unique=False)
    op.create_index(op.f('ix_report_drafts_report_id'), 'report_drafts', ['report_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_report_drafts_report_id'), table_name='report_drafts')
    op.drop_index(op.f('ix_report_drafts_case_id'), table_name='report_drafts')
    op.drop_table('report_drafts')
