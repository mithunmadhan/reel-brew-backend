"""add growth_plans table

Revision ID: cf32db7d6add
Revises: d2ffca6a4f1f
Create Date: 2026-09-20 11:11:31.588359

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cf32db7d6add'
down_revision: Union[str, Sequence[str], None] = 'd2ffca6a4f1f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'growth_plans',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('creator_id', sa.UUID(), nullable=False),
        sa.Column('plan_text', sa.Text(), nullable=False),
        sa.Column('based_on_post_count', sa.Integer(), nullable=False),
        sa.Column('generated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['creator_id'], ['creator_profiles.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_growth_plans_creator_id'), 'growth_plans', ['creator_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_growth_plans_creator_id'), table_name='growth_plans')
    op.drop_table('growth_plans')
