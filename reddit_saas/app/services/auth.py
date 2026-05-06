from datetime import datetime, timedelta, timezone
import logging

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import get_config
from app.models.user import User

logger = logging.getLogger(__name__)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Algorithm is a fixed constant, not a user-configurable setting
_JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire_minutes = int(get_config("access_token_expire_minutes"))
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=expire_minutes))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, get_config("secret_key"), algorithm=_JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, get_config("secret_key"), algorithms=[_JWT_ALGORITHM])
        return payload
    except JWTError:
        return None


def get_user_by_email(db: Session, email: str) -> User | None:
    try:
        return db.query(User).filter(User.email == email).first()
    except Exception as e:
        logger.error(f"DB error in get_user_by_email for {email}: {e}")
        return None


def create_user(db: Session, email: str, password: str, full_name: str | None = None) -> User:
    user = User(
        email=email,
        hashed_password=hash_password(password),
        full_name=full_name,
    )
    try:
        db.add(user)
        db.commit()
        db.refresh(user)
    except Exception as e:
        logger.error(f"DB error creating user {email}: {e}")
        db.rollback()
        raise
    return user


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    user = get_user_by_email(db, email)
    if not user or not verify_password(password, user.hashed_password):
        logger.warning("AUTH_FAILED | email=%s | reason=%s", email, "user_not_found" if not user else "bad_password")
        return None
    logger.info("AUTH_SUCCESS | email=%s | user_id=%s | is_superuser=%s", email, user.id, user.is_superuser)
    return user
