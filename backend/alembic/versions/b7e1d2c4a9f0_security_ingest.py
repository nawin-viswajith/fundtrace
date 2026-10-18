"""MFA, field-level encryption columns, evidence DLP results, ledger ingest log

Revision ID: b7e1d2c4a9f0
Revises: acf9ec214d54
Create Date: 2026-10-18 10:00:00.000000

Encrypted values are longer than the plaintext they replace, so the encrypted string columns become TEXT, and
evidence_items.extracted (encrypted JSON) becomes TEXT. Existing plaintext values stay readable and are
encrypted in place by app.crypto.backfill at start-up.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7e1d2c4a9f0'
down_revision: Union[str, Sequence[str], None] = 'acf9ec214d54'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('users') as b:
        b.add_column(sa.Column('mfa_enabled', sa.Boolean(), nullable=False, server_default='0'))
        b.add_column(sa.Column('mfa_secret', sa.Text(), nullable=True))
        b.add_column(sa.Column('mfa_last_step', sa.BigInteger(), nullable=True))
        b.add_column(sa.Column('mfa_recovery', sa.JSON(), nullable=True))
    with op.batch_alter_table('customers') as b:
        b.alter_column('display_name', type_=sa.Text(), existing_type=sa.String(length=128), existing_nullable=False)
    with op.batch_alter_table('accounts') as b:
        b.alter_column('holder_label', type_=sa.Text(), existing_type=sa.String(length=128), existing_nullable=False)
    with op.batch_alter_table('evidence_items') as b:
        b.alter_column('extracted', type_=sa.Text(), existing_type=sa.JSON(), existing_nullable=True)
        b.add_column(sa.Column('dlp', sa.JSON(), nullable=True))
    op.create_table(
        'ingest_events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('message_id', sa.String(length=128), nullable=False),
        sa.Column('channel', sa.String(length=16), nullable=False),
        sa.Column('source_system', sa.String(length=32), nullable=False),
        sa.Column('format', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('records_in', sa.Integer(), nullable=False),
        sa.Column('created', sa.Integer(), nullable=False),
        sa.Column('merged', sa.Integer(), nullable=False),
        sa.Column('duplicates', sa.Integer(), nullable=False),
        sa.Column('rejected', sa.JSON(), nullable=False),
        sa.Column('placeholder_accounts', sa.Integer(), nullable=False),
        sa.Column('cases_refreshed', sa.JSON(), nullable=False),
        sa.Column('error', sa.String(length=255), nullable=True),
        sa.Column('received_by', sa.String(length=128), nullable=False),
        sa.Column('received_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('message_id'),
    )


def downgrade() -> None:
    # Encrypted values do not fit the old column sizes: decrypt (set FIELD_ENCRYPTION_KEYS and re-save) before downgrading.
    op.drop_table('ingest_events')
    with op.batch_alter_table('evidence_items') as b:
        b.drop_column('dlp')
        b.alter_column('extracted', type_=sa.JSON(), existing_type=sa.Text(), existing_nullable=True)
    with op.batch_alter_table('accounts') as b:
        b.alter_column('holder_label', type_=sa.String(length=128), existing_type=sa.Text(), existing_nullable=False)
    with op.batch_alter_table('customers') as b:
        b.alter_column('display_name', type_=sa.String(length=128), existing_type=sa.Text(), existing_nullable=False)
    with op.batch_alter_table('users') as b:
        b.drop_column('mfa_recovery')
        b.drop_column('mfa_last_step')
        b.drop_column('mfa_secret')
        b.drop_column('mfa_enabled')
