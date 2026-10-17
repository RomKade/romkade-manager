"""genres

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-16 15:30:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('remote_file') as batch_op:
        batch_op.add_column(sa.Column('genre', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('genre_detail', sa.String(length=100), nullable=True))
        batch_op.create_index('ix_remote_file_genre', ['platform_id', 'genre'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('remote_file') as batch_op:
        batch_op.drop_index('ix_remote_file_genre')
        batch_op.drop_column('genre_detail')
        batch_op.drop_column('genre')
