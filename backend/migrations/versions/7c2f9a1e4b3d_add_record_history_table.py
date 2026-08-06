"""add record_history table

Revision ID: 7c2f9a1e4b3d
Revises: 1534727864f1
Create Date: 2026-08-06 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7c2f9a1e4b3d'
down_revision = '1534727864f1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'record_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entity_type', sa.String(length=64), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(length=32), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('actor_email', sa.String(length=255), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('start_day', sa.DateTime(), nullable=False),
        sa.Column('end_day', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('record_history', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_record_history_entity_type'), ['entity_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_record_history_entity_id'), ['entity_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_record_history_start_day'), ['start_day'], unique=False)
        batch_op.create_index(batch_op.f('ix_record_history_end_day'), ['end_day'], unique=False)


def downgrade():
    with op.batch_alter_table('record_history', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_record_history_end_day'))
        batch_op.drop_index(batch_op.f('ix_record_history_start_day'))
        batch_op.drop_index(batch_op.f('ix_record_history_entity_id'))
        batch_op.drop_index(batch_op.f('ix_record_history_entity_type'))
    op.drop_table('record_history')
