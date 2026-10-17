"""commandes des jeux (quelle touche fait quoi)

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-17 18:00:00
"""
from alembic import op
import sqlalchemy as sa
import app.db.models


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('game_controls',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('platform_id', sa.Integer(), nullable=False),
    sa.Column('normalized_title', sa.String(length=512), nullable=False),
    sa.Column('controls', sa.JSON(), nullable=False),
    sa.Column('notes', sa.JSON(), nullable=True),
    sa.Column('origin', sa.String(length=16), nullable=False),
    sa.Column('model', sa.String(length=40), nullable=True),
    sa.Column('updated_at', app.db.models.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['platform_id'], ['platform.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('platform_id', 'normalized_title')
    )


def downgrade() -> None:
    op.drop_table('game_controls')
