"""index for listing active signals by action

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-03 21:00:00
"""
from alembic import op


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index('ix_signal_status_action', 'signals', ['status', 'action', 'id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_signal_status_action', table_name='signals')
