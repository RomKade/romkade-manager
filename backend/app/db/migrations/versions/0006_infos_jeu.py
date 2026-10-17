"""informations de jeu (sortie, auteurs, résumé)

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-17 01:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None

COLUMNS = [
    sa.Column('release_year', sa.Integer(), nullable=True),
    sa.Column('release_date', sa.String(length=10), nullable=True),
    sa.Column('developer', sa.String(length=200), nullable=True),
    sa.Column('publisher', sa.String(length=200), nullable=True),
    sa.Column('franchise', sa.String(length=200), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('info_url', sa.String(length=500), nullable=True),
]


def upgrade() -> None:
    with op.batch_alter_table('remote_file') as batch_op:
        for column in COLUMNS:
            batch_op.add_column(column)
        batch_op.create_index('ix_remote_file_release_year', ['release_year'])


def downgrade() -> None:
    with op.batch_alter_table('remote_file') as batch_op:
        batch_op.drop_index('ix_remote_file_release_year')
        for column in reversed(COLUMNS):
            batch_op.drop_column(column.name)
