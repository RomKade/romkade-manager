"""remise à zéro du temps de jeu

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-17 20:00:00
"""
from alembic import op
import sqlalchemy as sa
import app.db.models


revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('play_reset',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('key', sa.String(length=1100), nullable=False),
    sa.Column('ra_baseline', sa.Integer(), nullable=False),
    sa.Column('reset_at', app.db.models.UTCDateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key')
    )


def downgrade() -> None:
    op.drop_table('play_reset')
