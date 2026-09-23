"""add audience demographics to social accounts

Revision ID: 86b35716caa6
Revises: cc5839248596
Create Date: 2026-09-17 18:46:37.329492

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '86b35716caa6'
down_revision: Union[str, Sequence[str], None] = 'cc5839248596'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('social_accounts', sa.Column('audience_demographics', sa.JSON(), nullable=True))
    op.add_column('social_accounts', sa.Column('demographics_synced_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('social_accounts', 'demographics_synced_at')
    op.drop_column('social_accounts', 'audience_demographics')
