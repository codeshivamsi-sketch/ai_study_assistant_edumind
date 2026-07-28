"""add quiz_id to messages

Revision ID: a5e2c8f4d1b9
Revises: 9def510cc11a
Create Date: 2026-07-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'a5e2c8f4d1b9'
down_revision: Union[str, Sequence[str], None] = '9def510cc11a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('quiz_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index(op.f('ix_messages_quiz_id'), 'messages', ['quiz_id'], unique=False)
    op.create_foreign_key(
        'fk_messages_quiz_id_quizzes', 'messages', 'quizzes', ['quiz_id'], ['id'], ondelete='SET NULL'
    )


def downgrade() -> None:
    op.drop_constraint('fk_messages_quiz_id_quizzes', 'messages', type_='foreignkey')
    op.drop_index(op.f('ix_messages_quiz_id'), table_name='messages')
    op.drop_column('messages', 'quiz_id')
