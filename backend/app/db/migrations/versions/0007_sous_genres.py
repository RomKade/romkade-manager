"""sous-genres

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-17 02:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('remote_file') as batch_op:
        batch_op.add_column(sa.Column('subgenre', sa.String(length=48), nullable=True))
        batch_op.create_index('ix_remote_file_subgenre', ['platform_id', 'subgenre'])


def downgrade() -> None:
    with op.batch_alter_table('remote_file') as batch_op:
        batch_op.drop_index('ix_remote_file_subgenre')
        batch_op.drop_column('subgenre')
