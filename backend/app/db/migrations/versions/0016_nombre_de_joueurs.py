"""nombre maximum de joueurs de chaque jeu (libretro-database « maxusers »)

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-22 21:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('remote_file') as batch_op:
        batch_op.add_column(sa.Column('players', sa.Integer(), nullable=True))
        batch_op.create_index('ix_remote_file_players', ['players'])


def downgrade() -> None:
    with op.batch_alter_table('remote_file') as batch_op:
        batch_op.drop_index('ix_remote_file_players')
        batch_op.drop_column('players')
