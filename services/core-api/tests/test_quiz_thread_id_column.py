import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from database import DATABASE_URL
from models import Document, Quiz

ALICE_ID = "11111111-1111-1111-1111-111111111111"


@pytest.mark.asyncio
async def test_quiz_thread_id_column_persists():
    engine = create_async_engine(DATABASE_URL)
    SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with SessionLocal() as session:
            document = Document(user_id=ALICE_ID, title="Thread id doc", status="ready")
            session.add(document)
            await session.commit()
            await session.refresh(document)

            quiz = Quiz(document_id=document.id, topic="Thread id quiz", questions=[], thread_id="thread-42")
            session.add(quiz)
            await session.commit()
            await session.refresh(quiz)

            assert quiz.thread_id == "thread-42"
    finally:
        await engine.dispose()
