"""add brand_aliases table, seeded from built-in translit table

Revision ID: b7e3a9c5d1f8
Revises: a1c4f0e2b7d3
Create Date: 2026-08-26 00:00:00.000000

"""
import os
import sys
from datetime import datetime

from alembic import op
import sqlalchemy as sa

# migrations/env.py уже добавляет backend/ в sys.path (см. импорт app.* там
# же) — но на всякий случай (миграции иногда запускают изолированно).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.services.builtin_brand_aliases import BUILTIN_BRAND_ALIASES  # noqa: E402


# revision identifiers, used by Alembic.
revision = 'b7e3a9c5d1f8'
down_revision = 'a1c4f0e2b7d3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'brand_aliases',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('alias', sa.String(length=256), nullable=False),
        sa.Column('canonical_make', sa.String(length=128), nullable=True),
        sa.Column('source', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('brand_aliases', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_brand_aliases_alias'), ['alias'], unique=True)
        batch_op.create_index(batch_op.f('ix_brand_aliases_canonical_make'), ['canonical_make'], unique=False)

    brand_aliases = sa.table(
        'brand_aliases',
        sa.column('alias', sa.String),
        sa.column('canonical_make', sa.String),
        sa.column('source', sa.String),
        sa.column('created_at', sa.DateTime),
        sa.column('updated_at', sa.DateTime),
    )
    now = datetime.utcnow()
    op.bulk_insert(
        brand_aliases,
        [
            {'alias': alias, 'canonical_make': canonical, 'source': 'builtin', 'created_at': now, 'updated_at': now}
            for alias, canonical in BUILTIN_BRAND_ALIASES.items()
        ],
    )


def downgrade():
    with op.batch_alter_table('brand_aliases', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_brand_aliases_canonical_make'))
        batch_op.drop_index(batch_op.f('ix_brand_aliases_alias'))
    op.drop_table('brand_aliases')
