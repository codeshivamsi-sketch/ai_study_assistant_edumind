"""add unique index on chats.document_id

Revision ID: 9def510cc11a
Revises: b7e14f9a2c63
Create Date: 2026-07-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9def510cc11a'
down_revision: Union[str, Sequence[str], None] = 'b7e14f9a2c63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index('ix_chats_document_id', table_name='chats')
    op.create_index(op.f('ix_chats_document_id'), 'chats', ['document_id'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_chats_document_id', table_name='chats')
    op.create_index(op.f('ix_chats_document_id'), 'chats', ['document_id'], unique=False)
