"""connaissances sur les jeux (Wikidata, Wikipédia, StrategyWiki) pour l'assistant

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-18 14:00:00
"""
from alembic import op
import sqlalchemy as sa
import app.db.models


revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('game_knowledge',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('platform_id', sa.Integer(), nullable=False),
    sa.Column('normalized_title', sa.String(length=512), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('wikidata_id', sa.String(length=20), nullable=True),
    sa.Column('sources', sa.JSON(), nullable=False),
    sa.Column('chunks', sa.Integer(), nullable=False),
    sa.Column('error', sa.String(length=300), nullable=True),
    sa.Column('fetched_at', app.db.models.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['platform_id'], ['platform.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('platform_id', 'normalized_title')
    )
    op.create_table('knowledge_chunk',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('platform_id', sa.Integer(), nullable=False),
    sa.Column('normalized_title', sa.String(length=512), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('lang', sa.String(length=2), nullable=False),
    sa.Column('page', sa.String(length=300), nullable=False),
    sa.Column('section', sa.String(length=300), nullable=False),
    sa.Column('url', sa.String(length=600), nullable=False),
    sa.Column('license', sa.String(length=40), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['platform_id'], ['platform.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_knowledge_chunk_game', 'knowledge_chunk', ['platform_id', 'normalized_title'])


def downgrade() -> None:
    op.drop_index('ix_knowledge_chunk_game', table_name='knowledge_chunk')
    op.drop_table('knowledge_chunk')
    op.drop_table('game_knowledge')
