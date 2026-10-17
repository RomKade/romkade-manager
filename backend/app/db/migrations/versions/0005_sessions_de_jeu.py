"""sessions de jeu

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-16 19:00:00
"""
from alembic import op
import sqlalchemy as sa
import app.db.models


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('play_session',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('rom_path', sa.String(length=1024), nullable=False),
    sa.Column('platform_dir', sa.String(length=100), nullable=True),
    sa.Column('game_id', sa.Integer(), nullable=True),
    sa.Column('title', sa.String(length=512), nullable=False),
    sa.Column('process', sa.String(length=40), nullable=True),
    sa.Column('started_at', app.db.models.UTCDateTime(), nullable=False),
    sa.Column('ended_at', app.db.models.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['game_id'], ['remote_file.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_play_session_game_id', 'play_session', ['game_id'], unique=False)
    op.create_index('ix_play_session_started_at', 'play_session', ['started_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_play_session_started_at', table_name='play_session')
    op.drop_index('ix_play_session_game_id', table_name='play_session')
    op.drop_table('play_session')
