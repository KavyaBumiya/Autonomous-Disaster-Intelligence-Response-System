"""Auth endpoints: login, me."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import verify_password, create_access_token
from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.user import User

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    expires_in: int


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    # Update last_login
    user.last_login = datetime.now(timezone.utc)
    await db.commit()

    token = create_access_token(user.id, user.role)
    from app.core.config import get_settings
    return LoginResponse(
        access_token=token,
        role=user.role,
        expires_in=get_settings().jwt_expire_minutes * 60,
    )


@router.get("/me")
async def me(current_user: dict = Depends(get_current_user)):
    return current_user
