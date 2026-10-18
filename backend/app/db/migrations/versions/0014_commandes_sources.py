"""commandes des jeux : passages (Wikipédia, StrategyWiki) sur lesquels l'IA s'est appuyée

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-18 22:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('game_controls') as batch:
        batch.add_column(sa.Column('sources', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('game_controls') as batch:
        batch.drop_column('sources')
