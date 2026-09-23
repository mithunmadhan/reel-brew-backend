"""add follower_count to social accounts

Revision ID: d2ffca6a4f1f
Revises: 86b35716caa6
Create Date: 2026-09-17 18:58:56.895050

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2ffca6a4f1f'
down_revision: Union[str, Sequence[str], None] = '86b35716caa6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('social_accounts', sa.Column('follower_count', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('social_accounts', 'follower_count')
