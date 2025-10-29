"""
Authentication utilities
"""
import os
from datetime import datetime, timedelta
from typing import Optional, Annotated
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Cookie
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT settings
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-this-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

# Cookie name for bearer token
BEARER_TOKEN_COOKIE_NAME = "access_token"

# Security scheme for Authorization header (fallback)
security = HTTPBearer(auto_error=False)

# Default user credentials (in production, use a database)
# username: admin, password: admin (change these!)
DEFAULT_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
DEFAULT_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")

# In-memory user store (in production, use a database)
# Password hash will be computed lazily on first access
_users_db = None


def get_users_db():
    """Get or initialize the users database with lazy password hashing"""
    global _users_db
    if _users_db is None:
        _users_db = {
            DEFAULT_USERNAME: {
                "username": DEFAULT_USERNAME,
                "hashed_password": pwd_context.hash(DEFAULT_PASSWORD),
            }
        }
    return _users_db

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password"""
    return pwd_context.hash(password)


def authenticate_user(username: str, password: str) -> Optional[dict]:
    """Authenticate a user and return user data if valid"""
    users_db = get_users_db()
    user = users_db.get(username)
    if not user:
        return None
    if not verify_password(password, user["hashed_password"]):
        return None
    return user


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(
    token_cookie: Annotated[Optional[str], Cookie(alias=BEARER_TOKEN_COOKIE_NAME)] = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """
    Get the current authenticated user from JWT token.
    Supports both cookie-based and Authorization header authentication.
    Priority: cookie > Authorization header
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    # Try to get token from cookie first, then fall back to Authorization header
    token = None
    if token_cookie and token_cookie.strip():  # Check for non-empty cookie
        token = token_cookie
    elif credentials:
        token = credentials.credentials
    
    if not token or not token.strip():  # Reject empty tokens
        raise credentials_exception
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    users_db = get_users_db()
    user = users_db.get(username)
    if user is None:
        raise credentials_exception
    
    return user

