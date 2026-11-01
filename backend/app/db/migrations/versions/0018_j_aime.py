"""jeux marqués « J'aime » (pouce en haut), par console

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-01 17:00:00
"""
from alembic import op
import sqlalchemy as sa
import app.db.models


revision = '0018'
down_revision = '0017'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('liked_game',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('file_id', sa.Integer(), nullable=False),
    sa.Column('console', sa.String(length=100), nullable=True),
    sa.Column('created_at', app.db.models.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['file_id'], ['remote_file.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('console', 'file_id')
    )
    op.create_index('ix_liked_game_file_id', 'liked_game', ['file_id'])


def downgrade() -> None:
    op.drop_index('ix_liked_game_file_id', table_name='liked_game')
    op.drop_table('liked_game')
