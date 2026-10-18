"""customer portal: customer logins and dispute intake details

Revision ID: e8a3f1c06d27
Revises: d41c7a2e5b93
Create Date: 2026-10-18 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e8a3f1c06d27'
down_revision: Union[str, Sequence[str], None] = 'd41c7a2e5b93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('users') as b:
        b.add_column(sa.Column('customer_id', sa.String(length=32), nullable=True))
        b.create_index(b.f('ix_users_customer_id'), ['customer_id'], unique=False)
        b.create_foreign_key('fk_users_customer_id_customers', 'customers', ['customer_id'], ['id'])
    with op.batch_alter_table('dispute_cases') as b:
        b.add_column(sa.Column('channel', sa.String(length=16), nullable=True))
        b.add_column(sa.Column('intake', sa.Text(), nullable=True))  # encrypted JSON


def downgrade() -> None:
    with op.batch_alter_table('dispute_cases') as b:
        b.drop_column('intake')
        b.drop_column('channel')
    with op.batch_alter_table('users') as b:
        b.drop_constraint('fk_users_customer_id_customers', type_='foreignkey')
        b.drop_index(b.f('ix_users_customer_id'))
        b.drop_column('customer_id')
