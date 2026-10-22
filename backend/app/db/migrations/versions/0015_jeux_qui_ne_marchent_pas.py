"""jeux signalés comme ne fonctionnant pas, par console

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-20 23:00:00
"""
from alembic import op
import sqlalchemy as sa
import app.db.models


revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('broken_game',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('file_id', sa.Integer(), nullable=False),
    sa.Column('console', sa.String(length=100), nullable=True),
    sa.Column('created_at', app.db.models.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['file_id'], ['remote_file.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('console', 'file_id')
    )
    op.create_index('ix_broken_game_file_id', 'broken_game', ['file_id'])


def downgrade() -> None:
    op.drop_index('ix_broken_game_file_id', table_name='broken_game')
    op.drop_table('broken_game')
