"""favorited predictions

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-30 20:00:00
"""
from alembic import op
import sqlalchemy as sa
import app.db


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'favorites',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('token_id', sa.Integer(), nullable=False),
        sa.Column('signal_id', sa.Integer(), nullable=True),
        sa.Column('favorited_at', app.db.UTCDateTime(timezone=True), nullable=False),
        sa.Column('signal_at', app.db.UTCDateTime(timezone=True), nullable=False),
        sa.Column('action', sa.String(length=16), nullable=True),
        sa.Column('strength', sa.String(length=16), nullable=True),
        sa.Column('headline', sa.String(length=256), nullable=True),
        sa.Column('reasons', sa.JSON(), nullable=False),
        sa.Column('reference_price_usd', sa.Float(), nullable=True),
        sa.Column('price_at_favorite', sa.Float(), nullable=True),
        sa.Column('gain_at_favorite', sa.Float(), nullable=True),
        sa.Column('max_gain_until_favorite', sa.Float(), nullable=True),
        sa.Column('min_gain_until_favorite', sa.Float(), nullable=True),
        sa.Column('liquidity_at_favorite', sa.Float(), nullable=True),
        sa.Column('specs', sa.JSON(), nullable=False),
        sa.Column('rules_version', sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['token_id'], ['tokens.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['signal_id'], ['signals.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_favorite_user_time', 'favorites', ['user_id', 'favorited_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_favorite_user_time', table_name='favorites')
    op.drop_table('favorites')
