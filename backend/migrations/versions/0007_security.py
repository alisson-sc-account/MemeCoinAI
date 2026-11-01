"""security reports, wallet profiles and permanent rug mark

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-30 23:30:00
"""
from alembic import op
import sqlalchemy as sa
import app.db


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('tokens', schema=None) as batch_op:
        batch_op.add_column(sa.Column('rugged_at', app.db.UTCDateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('rug_reason', sa.Text(), nullable=True))
    op.create_table(
        'security_reports',
        sa.Column('token_id', sa.Integer(), nullable=False),
        sa.Column('checked_at', app.db.UTCDateTime(timezone=True), nullable=False),
        sa.Column('verdict', sa.String(length=16), nullable=False),
        sa.Column('checks', sa.JSON(), nullable=False),
        sa.Column('holders', sa.JSON(), nullable=False),
        sa.Column('facts', sa.JSON(), nullable=False),
        sa.Column('rules_version', sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(['token_id'], ['tokens.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('token_id'),
    )
    op.create_table(
        'wallet_profiles',
        sa.Column('address', sa.String(length=64), nullable=False),
        sa.Column('first_seen_at', app.db.UTCDateTime(timezone=True), nullable=True),
        sa.Column('signatures', sa.Integer(), nullable=False),
        sa.Column('complete', sa.Boolean(), nullable=False),
        sa.Column('funder', sa.String(length=64), nullable=True),
        sa.Column('checked_at', app.db.UTCDateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('address'),
    )


def downgrade() -> None:
    op.drop_table('wallet_profiles')
    op.drop_table('security_reports')
    with op.batch_alter_table('tokens', schema=None) as batch_op:
        batch_op.drop_column('rug_reason')
        batch_op.drop_column('rugged_at')
