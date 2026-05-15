from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

from app.database import get_db
from app.services.auth import authenticate_user, create_user, create_access_token, get_user_by_email

router = APIRouter()


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/register", response_model=TokenResponse)
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    existing = get_user_by_email(db, data.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = create_user(db, email=data.email, password=data.password, full_name=data.full_name)
    token = create_access_token(data={
        "sub": str(user.id),
        "email": user.email,
        "full_name": user.full_name or "",
        "role": user.user_role.value,
        "is_superuser": user.is_superuser,
    })
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = authenticate_user(db, data.email, data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(data={
        "sub": str(user.id),
        "email": user.email,
        "full_name": user.full_name or "",
        "role": user.user_role.value,
        "is_superuser": user.is_superuser,
    })
    return TokenResponse(access_token=token)
