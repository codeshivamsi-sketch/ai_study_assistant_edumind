"""create edumind schema

Revision ID: c1c8df1bcff2
Revises:
Create Date: 2026-07-17 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c1c8df1bcff2'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("DROP TABLE IF EXISTS loan_applications")

    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)

    op.create_table(
        'documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('uploaded','processing','ready','failed')", name='documents_status_check'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_documents_user_id'), 'documents', ['user_id'], unique=False)

    op.create_table(
        'quizzes',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('topic', sa.String(), nullable=False),
        sa.Column('questions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_quizzes_document_id'), 'quizzes', ['document_id'], unique=False)

    op.create_table(
        'quiz_attempts',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('quiz_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('answers', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('score', sa.Numeric(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['quiz_id'], ['quizzes.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_quiz_attempts_quiz_id'), 'quiz_attempts', ['quiz_id'], unique=False)
    op.create_index(op.f('ix_quiz_attempts_user_id'), 'quiz_attempts', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('quiz_attempts')
    op.drop_table('quizzes')
    op.drop_table('documents')
    op.drop_table('users')
