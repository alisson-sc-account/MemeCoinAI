"""token last checked: rotation must advance even when the source returns nothing

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-02 01:00:00
"""
from alembic import op
import sqlalchemy as sa
import app.db


revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('tokens', schema=None) as batch_op:
        batch_op.add_column(sa.Column('last_checked_at', app.db.UTCDateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('tokens', schema=None) as batch_op:
        batch_op.drop_column('last_checked_at')
