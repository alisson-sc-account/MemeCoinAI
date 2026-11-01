"""token heat for collection priority

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-30 22:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('tokens', schema=None) as batch_op:
        batch_op.add_column(sa.Column('heat', sa.Float(), server_default='0', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('tokens', schema=None) as batch_op:
        batch_op.drop_column('heat')
