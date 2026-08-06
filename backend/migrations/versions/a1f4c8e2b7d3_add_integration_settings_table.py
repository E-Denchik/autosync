"""add integration_settings table

Revision ID: a1f4c8e2b7d3
Revises: 7c2f9a1e4b3d
Create Date: 2026-08-06 23:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1f4c8e2b7d3'
down_revision = '7c2f9a1e4b3d'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('integration_settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('value', sa.Text(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('integration_settings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_integration_settings_key'), ['key'], unique=True)


def downgrade():
    with op.batch_alter_table('integration_settings', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_integration_settings_key'))
    op.drop_table('integration_settings')
