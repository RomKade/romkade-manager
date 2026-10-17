"""jeux favoris

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-17 19:00:00
"""
from alembic import op
import sqlalchemy as sa
import app.db.models


revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('favorite',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('file_id', sa.Integer(), nullable=False),
    sa.Column('created_at', app.db.models.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['file_id'], ['remote_file.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('file_id')
    )


def downgrade() -> None:
    op.drop_table('favorite')
