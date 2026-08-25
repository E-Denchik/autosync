"""add contract_qty to part_matches

Revision ID: d2f6a8c1b4e7
Revises: c4f8b2e6a913
Create Date: 2026-08-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd2f6a8c1b4e7'
down_revision = 'c4f8b2e6a913'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('part_matches', schema=None) as batch_op:
        batch_op.add_column(sa.Column('contract_qty', sa.Numeric(precision=12, scale=3), nullable=True))


def downgrade():
    with op.batch_alter_table('part_matches', schema=None) as batch_op:
        batch_op.drop_column('contract_qty')
