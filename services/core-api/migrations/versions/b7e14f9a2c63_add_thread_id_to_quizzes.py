"""add thread_id to quizzes

Revision ID: b7e14f9a2c63
Revises: d3f6a91c8e27
Create Date: 2026-07-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e14f9a2c63'
down_revision: Union[str, Sequence[str], None] = 'd3f6a91c8e27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('quizzes', sa.Column('thread_id', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('quizzes', 'thread_id')
