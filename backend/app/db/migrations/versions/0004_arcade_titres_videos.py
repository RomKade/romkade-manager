"""titres arcade et vidéos

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-16 16:00:00
"""
from alembic import op
import sqlalchemy as sa
import app.db.models


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('remote_file') as batch_op:
        batch_op.add_column(sa.Column('full_title', sa.String(length=512), nullable=True))
    op.create_table('game_video',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('platform_id', sa.Integer(), nullable=False),
    sa.Column('normalized_title', sa.String(length=512), nullable=False),
    sa.Column('query', sa.String(length=300), nullable=False),
    sa.Column('videos', sa.JSON(), nullable=False),
    sa.Column('fetched_at', app.db.models.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['platform_id'], ['platform.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('platform_id', 'normalized_title')
    )


def downgrade() -> None:
    op.drop_table('game_video')
    with op.batch_alter_table('remote_file') as batch_op:
        batch_op.drop_column('full_title')
