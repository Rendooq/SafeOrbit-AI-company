from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from pydantic import BaseModel, Field
from datetime import datetime

from database import get_db
from models import Business, User, Integration
from dependencies import get_current_user

router = APIRouter(prefix="/api/v1", tags=["Schools & Branches"])

# --- Pydantic Schemas ---

class BranchCreate(BaseModel):
    name: str = Field(..., example="Філія Центр")
    address: Optional[str] = Field(None, example="вул. Хрещатик, 1")
    city: Optional[str] = Field(None, example="Київ")

class BranchResponse(BaseModel):
    id: int
    school_id: int
    name: str
    address: Optional[str]
    city: Optional[str]
    is_active: bool

class IntegrationCreate(BaseModel):
    provider: str = Field(..., example="telegram")
    name: str = Field(..., example="Чат-бот Центрального філіалу")
    token: str = Field(..., example="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
    is_active: bool = True

class IntegrationResponse(BaseModel):
    id: int
    branch_id: int
    provider: str
    name: str
    is_active: bool
    created_at: datetime

# --- RBAC Dependency Helpers ---

async def verify_school_access(school_id: int, user: User, db: AsyncSession):
    """
    Перевірка прав доступу: school_owner має доступ до школи, 
    admin (менеджер філії) не має доступу до керування всією школою.
    """
    if user.role == "superadmin":
        return True
        
    # Власник школи має parent_id = None і його business_id == school_id
    if user.role == "owner" and user.business_id == school_id:
        biz = await db.get(Business, school_id)
        if biz and not biz.parent_id and biz.type == "school":
            return True
            
    raise HTTPException(status_code=403, detail="Доступ заборонено. Потрібні права school_owner.")

async def verify_branch_access(branch_id: int, user: User, db: AsyncSession):
    """
    Власник школи має доступ до всіх своїх філій.
    Менеджер (admin) філії має доступ ТІЛЬКИ до своєї філії.
    """
    if user.role == "superadmin":
        return True
        
    branch = await db.get(Business, branch_id)
    if not branch or not branch.parent_id:
        raise HTTPException(status_code=404, detail="Філію не знайдено.")
        
    # Якщо це менеджер саме цієї філії
    if user.role == "admin" and user.business_id == branch_id:
        return True
        
    # Якщо це власник школи, якій належить ця філія
    if user.role == "owner" and user.business_id == branch.parent_id:
        return True
        
    raise HTTPException(status_code=403, detail="Недостатньо прав для доступу до цієї філії.")

# --- API Endpoints ---

@router.get("/schools/{school_id}/branches", response_model=List[BranchResponse])
async def get_school_branches(
    school_id: int, 
    user: User = Depends(get_current_user), 
    db: AsyncSession = Depends(get_db)
):
    """Отримати список всіх філій школи (Тільки для school_owner)"""
    await verify_school_access(school_id, user, db)
    
    stmt = select(Business).where(Business.parent_id == school_id)
    branches = (await db.execute(stmt)).scalars().all()
    
    return [
        BranchResponse(
            id=b.id, school_id=b.parent_id, name=b.name, 
            address=b.address, city=b.city, is_active=b.is_active
        ) for b in branches
    ]

@router.post("/schools/{school_id}/branches", response_model=BranchResponse, status_code=201)
async def create_branch(
    school_id: int, 
    payload: BranchCreate, 
    user: User = Depends(get_current_user), 
    db: AsyncSession = Depends(get_db)
):
    """Створити нову філію в рамках школи"""
    await verify_school_access(school_id, user, db)
    
    school = await db.get(Business, school_id)
    
    new_branch = Business(
        name=payload.name,
        address=payload.address,
        city=payload.city,
        parent_id=school_id,
        type=school.type, # Наслідуємо тип "school"
        plan_type=school.plan_type,
        has_ai_bot=True,
        integration_enabled=True
    )
    db.add(new_branch)
    await db.commit()
    await db.refresh(new_branch)
    
    return BranchResponse(
        id=new_branch.id, school_id=new_branch.parent_id, name=new_branch.name, 
        address=new_branch.address, city=new_branch.city, is_active=new_branch.is_active
    )

@router.post("/branches/{branch_id}/integrations", response_model=IntegrationResponse, tags=["Integrations"])
async def add_branch_integration(
    branch_id: int,
    payload: IntegrationCreate,
    user: User = Depends(get_current_user), 
    db: AsyncSession = Depends(get_db)
):
    """
    Додати ізольовану інтеграцію (наприклад, Telegram токен) суворо до конкретної філії.
    """
    await verify_branch_access(branch_id, user, db)
    
    integration = Integration(
        business_id=branch_id, # branch_id це по суті business_id філії
        provider=payload.provider,
        name=payload.name,
        token=payload.token,
        is_active=payload.is_active
    )
    db.add(integration)
    await db.commit()
    await db.refresh(integration)
    
    return IntegrationResponse(
        id=integration.id, branch_id=integration.business_id, 
        provider=integration.provider, name=integration.name, 
        is_active=integration.is_active, created_at=datetime.utcnow()
    )