"""descriptions des jeux (fr, en, es)

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-17 03:00:00
"""
from alembic import op
import sqlalchemy as sa
import app.db.models


revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('game_text',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('platform_id', sa.Integer(), nullable=False),
    sa.Column('normalized_title', sa.String(length=512), nullable=False),
    sa.Column('lang', sa.String(length=2), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('origin', sa.String(length=16), nullable=False),
    sa.Column('model', sa.String(length=40), nullable=True),
    sa.Column('created_at', app.db.models.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['platform_id'], ['platform.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('platform_id', 'normalized_title', 'lang')
    )


def downgrade() -> None:
    op.drop_table('game_text')
