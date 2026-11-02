"""pop-in « Tu as aimé ? » après une partie : jeux pour lesquels elle a été fermée sans avis, par console

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-02 10:00:00
"""
from alembic import op
import sqlalchemy as sa
import app.db.models


revision = '0019'
down_revision = '0018'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('opinion_asked',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('file_id', sa.Integer(), nullable=False),
    sa.Column('console', sa.String(length=100), nullable=True),
    sa.Column('created_at', app.db.models.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['file_id'], ['remote_file.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('console', 'file_id')
    )
    op.create_index('ix_opinion_asked_file_id', 'opinion_asked', ['file_id'])


def downgrade() -> None:
    op.drop_index('ix_opinion_asked_file_id', table_name='opinion_asked')
    op.drop_table('opinion_asked')
