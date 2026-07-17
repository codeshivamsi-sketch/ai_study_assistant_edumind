"""seed test users

Revision ID: e64775fbbdec
Revises: c1c8df1bcff2
Create Date: 2026-07-17 19:05:00.000000

"""
from typing import Sequence, Union
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e64775fbbdec'
down_revision: Union[str, Sequence[str], None] = 'c1c8df1bcff2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

users_table = sa.table(
    'users',
    sa.column('id', postgresql.UUID(as_uuid=True)),
    sa.column('email', sa.String),
    sa.column('name', sa.String),
    sa.column('created_at', sa.DateTime(timezone=True)),
)

_seeded_at = datetime.now(timezone.utc)

SEED_USERS = [
    {
        'id': '11111111-1111-1111-1111-111111111111',
        'email': 'alice@edumind.test',
        'name': 'Alice',
        'created_at': _seeded_at,
    },
    {
        'id': '22222222-2222-2222-2222-222222222222',
        'email': 'bob@edumind.test',
        'name': 'Bob',
        'created_at': _seeded_at,
    },
]


def upgrade() -> None:
    """Upgrade schema."""
    op.bulk_insert(users_table, SEED_USERS)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "DELETE FROM users WHERE id IN "
        "('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222')"
    )
