"""jeux marqués « Je n'aime pas », par console

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-01 10:00:00
"""
from alembic import op
import sqlalchemy as sa
import app.db.models


revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('disliked_game',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('file_id', sa.Integer(), nullable=False),
    sa.Column('console', sa.String(length=100), nullable=True),
    sa.Column('created_at', app.db.models.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['file_id'], ['remote_file.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('console', 'file_id')
    )
    op.create_index('ix_disliked_game_file_id', 'disliked_game', ['file_id'])


def downgrade() -> None:
    op.drop_index('ix_disliked_game_file_id', table_name='disliked_game')
    op.drop_table('disliked_game')
