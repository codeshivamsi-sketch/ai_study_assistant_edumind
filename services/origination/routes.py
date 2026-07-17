from fastapi import APIRouter, HTTPException, Depends, Header
from database import AsyncSessionLocal
from models import LoanApplication, LoanStatus
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from worker import run_credit_check, celery_app
from celery.result import AsyncResult
from logger import log

router = APIRouter()

class LoanApplicationRequest(BaseModel):
    customer_id: str
    amount: float
    purpose: str

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

@router.post("/applications")
async def create_application(
    request: LoanApplicationRequest, 
    db: AsyncSession = Depends(get_db),
    idempotency_key: str = Header(..., alias="idempotency-key")
):
    # Check if we've seen this key before
    result = await db.execute(
        select(LoanApplication).where(LoanApplication.idempotency_key == idempotency_key)
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    # First time seeing this key - create the application
    application = LoanApplication(
        customer_id = request.customer_id,
        amount = request.amount,
        purpose = request.purpose,
        status = LoanStatus.DRAFT,
        idempotency_key=idempotency_key
    )
    db.add(application)
    await db.commit()
    await db.refresh(application)
    log.info("application_created", loan_id=str(application.id), customer_id=application.customer_id, amount=application.amount)
    return application

@router.get("/applications/{app_id}")
async def get_application(app_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(LoanApplication).where(LoanApplication.id == app_id))
    application = result.scalar_one_or_none()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    return application

@router.patch("/applications/{app_id}/submit")
async def submit_application(app_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(LoanApplication).where(LoanApplication.id == app_id))
    application = result.scalar_one_or_none()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    if application.status != LoanStatus.DRAFT:
        raise HTTPException(status_code=400, detail="Only draft application can be submitted")
    application.status = LoanStatus.SUBMITTED
    await db.commit()
    await db.refresh(application)

    # Fire background job - don't wait for it
    task = run_credit_check.delay(str(application.id), application.customer_id)

    return {"application": application, "credit_check_task_id": task.id}

@router.get("/tasks/{task_id}")
def get_task_result(task_id: str):
    result = AsyncResult(task_id, app=celery_app)
    return {
        "task_id": task_id,
        "status": result.status,
        "result": result.result
    }