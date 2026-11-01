"""live fast lane: watch list, quick quotes, service heartbeats

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-29 23:50:00
"""
from alembic import op
import sqlalchemy as sa
import app.db


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'live_watch',
        sa.Column('token_id', sa.Integer(), nullable=False),
        sa.Column('first_requested_at', app.db.UTCDateTime(timezone=True), nullable=False),
        sa.Column('last_requested_at', app.db.UTCDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['token_id'], ['tokens.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('token_id'),
    )
    op.create_table(
        'live_quotes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('token_id', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(length=32), nullable=False),
        sa.Column('received_at', app.db.UTCDateTime(timezone=True), nullable=False),
        sa.Column('price_usd', sa.Float(), nullable=False),
        sa.Column('liquidity_usd', sa.Float(), nullable=True),
        sa.Column('block_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['token_id'], ['tokens.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_live_token_received', 'live_quotes', ['token_id', 'received_at'], unique=False)
    op.create_table(
        'service_heartbeats',
        sa.Column('name', sa.String(length=32), nullable=False),
        sa.Column('started_at', app.db.UTCDateTime(timezone=True), nullable=False),
        sa.Column('last_tick_at', app.db.UTCDateTime(timezone=True), nullable=True),
        sa.Column('last_ok_at', app.db.UTCDateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('interval_seconds', sa.Integer(), nullable=False),
        sa.Column('watched', sa.Integer(), nullable=False),
        sa.Column('quoted', sa.Integer(), nullable=False),
        sa.Column('last_duration_ms', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('name'),
    )


def downgrade() -> None:
    op.drop_table('service_heartbeats')
    op.drop_index('ix_live_token_received', table_name='live_quotes')
    op.drop_table('live_quotes')
    op.drop_table('live_watch')
