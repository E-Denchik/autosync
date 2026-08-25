"""add raw_import_rows table (staging for uploaded files before matching)

Revision ID: c4f8b2e6a913
Revises: b7e3a9c5d1f8
Create Date: 2026-08-26 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4f8b2e6a913'
down_revision = 'b7e3a9c5d1f8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'raw_import_rows',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('contract_id', sa.Integer(), nullable=True),
        sa.Column('repair_order_id', sa.Integer(), nullable=True),
        sa.Column('row_kind', sa.String(length=24), nullable=False),
        sa.Column('source_filename', sa.String(length=512), nullable=True),
        sa.Column('row_index', sa.Integer(), nullable=False),
        sa.Column('raw_data', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['contract_id'], ['contracts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['repair_order_id'], ['repair_orders.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('raw_import_rows', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_raw_import_rows_contract_id'), ['contract_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_raw_import_rows_repair_order_id'), ['repair_order_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_raw_import_rows_row_kind'), ['row_kind'], unique=False)
        batch_op.create_index(batch_op.f('ix_raw_import_rows_status'), ['status'], unique=False)


def downgrade():
    with op.batch_alter_table('raw_import_rows', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_raw_import_rows_status'))
        batch_op.drop_index(batch_op.f('ix_raw_import_rows_row_kind'))
        batch_op.drop_index(batch_op.f('ix_raw_import_rows_repair_order_id'))
        batch_op.drop_index(batch_op.f('ix_raw_import_rows_contract_id'))
    op.drop_table('raw_import_rows')
