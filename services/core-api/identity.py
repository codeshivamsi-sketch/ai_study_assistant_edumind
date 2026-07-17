from fastapi import Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database import get_db
from models import User
import uuid

async def get_current_user(
    x_user_id: str = Header(None, alias="X-User-Id"),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not x_user_id:
        raise HTTPException(status_code=401, detail="X-User-Id header is required")
    try:
        user_id = uuid.UUID(x_user_id)
    except ValueError:
        raise HTTPException(status_code=401, detail="Unknown user")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Unknown user")
    return user
