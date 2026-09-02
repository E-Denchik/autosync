"""add llm_extraction_cache table (cache LLM table-extraction by chunk hash)

Revision ID: f1a2b3c4d5e6
Revises: d2f6a8c1b4e7
Create Date: 2026-09-02 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f1a2b3c4d5e6'
down_revision = 'd2f6a8c1b4e7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'llm_extraction_cache',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cache_key', sa.String(length=64), nullable=False),
        sa.Column('rows', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('llm_extraction_cache', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_llm_extraction_cache_cache_key'), ['cache_key'], unique=True
        )


def downgrade():
    with op.batch_alter_table('llm_extraction_cache', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_llm_extraction_cache_cache_key'))
    op.drop_table('llm_extraction_cache')
