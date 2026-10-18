"""favoris par console

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-18 10:00:00

Un favori est rattaché à la console où il a été mis (empreinte de sa clé SSH). La table est recréée : SQLite ne
sait pas retirer la contrainte d'unicité sans nom sur file_id. Les favoris existants gardent console = NULL
(montrés sur toute console où le jeu est présent).
"""
from alembic import op
import sqlalchemy as sa
import app.db.models


revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('favorite_new',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('file_id', sa.Integer(), nullable=False),
    sa.Column('console', sa.String(length=100), nullable=True),
    sa.Column('created_at', app.db.models.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['file_id'], ['remote_file.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('console', 'file_id')
    )
    op.execute("INSERT INTO favorite_new (id, file_id, console, created_at) SELECT id, file_id, NULL, created_at FROM favorite")
    op.drop_table('favorite')
    op.rename_table('favorite_new', 'favorite')
    op.create_index('ix_favorite_file_id', 'favorite', ['file_id'])


def downgrade() -> None:
    op.create_table('favorite_old',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('file_id', sa.Integer(), nullable=False),
    sa.Column('created_at', app.db.models.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['file_id'], ['remote_file.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('file_id')
    )
    op.execute("INSERT OR IGNORE INTO favorite_old (id, file_id, created_at) SELECT id, file_id, created_at FROM favorite")
    op.drop_table('favorite')
    op.rename_table('favorite_old', 'favorite')
