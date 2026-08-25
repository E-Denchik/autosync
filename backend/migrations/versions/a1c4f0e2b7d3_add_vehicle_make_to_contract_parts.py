"""add vehicle_make to contract_parts

Revision ID: a1c4f0e2b7d3
Revises: 04cbb9027e52
Create Date: 2026-08-25 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1c4f0e2b7d3'
down_revision = '04cbb9027e52'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('contract_parts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('vehicle_make', sa.String(length=128), nullable=True))
        batch_op.create_index(batch_op.f('ix_contract_parts_vehicle_make'), ['vehicle_make'], unique=False)


def downgrade():
    with op.batch_alter_table('contract_parts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_contract_parts_vehicle_make'))
        batch_op.drop_column('vehicle_make')
