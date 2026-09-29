import hmac

from fastapi import APIRouter, Depends, status, HTTPException
from fastapi import Header
from fastapi.security.oauth2 import OAuth2PasswordRequestForm
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..schemas.user import UserCreate, UserResponse, RefreshAccessTokenRequest, TokenPayload, BootstrapAdminRequest, AdminUserResponse

from ..utils import password_manager, oauth2
from ..database import get_db

from shared.models import User, UserType

from config import BOOTSTRAP_ADMIN_SECRET, DUMMY_PASS

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)

DUMMY_PASSWORD = password_manager.hash(DUMMY_PASS)

@router.post('/register', status_code=status.HTTP_201_CREATED, response_model=UserResponse)
def register(new_user: UserCreate, db: Session = Depends(get_db)):

    if (new_user.password != new_user.conf_password):
        raise HTTPException(detail="confirm password and given password don't match", status_code=status.HTTP_400_BAD_REQUEST)

    user = db.query(User).filter(User.username == new_user.username).first()
    if not user:
        user = db.query(User).filter(User.email == new_user.email).first()
    
    if user:
        raise HTTPException(detail="user with this username or email already exists", status_code=status.HTTP_409_CONFLICT)
    
    hashed_password = password_manager.hash(new_user.password)
    new_user = User(username=new_user.username, email=new_user.email, password_hash=hashed_password)
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return new_user

@router.post('/bootstrap-admin', status_code=status.HTTP_200_OK, response_model=AdminUserResponse)
def bootstrap_first_admin(
    request: BootstrapAdminRequest,
    bootstrap_secret: str | None = Header(default=None, alias="X-Bootstrap-Secret"),
    db: Session = Depends(get_db),
):
    if not BOOTSTRAP_ADMIN_SECRET:
        raise HTTPException(
            detail="Admin bootstrap is disabled",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    if bootstrap_secret is None or not hmac.compare_digest(
        bootstrap_secret.encode("utf-8"),
        BOOTSTRAP_ADMIN_SECRET.encode("utf-8"),
    ):
        raise HTTPException(
            detail="Invalid bootstrap secret",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    with db.begin():
        db.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": 781240193})

        if db.query(User).filter(User.user_type == UserType.ADMIN).first():
            raise HTTPException(
                detail="An admin user already exists",
                status_code=status.HTTP_409_CONFLICT,
            )

        user = db.query(User).filter(User.username == request.username).first()
        if not user:
            raise HTTPException(
                detail="User not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        user.user_type = UserType.ADMIN

    db.refresh(user)
    return {"username": user.username, "user_type": user.user_type}

@router.post('/login', status_code=status.HTTP_200_OK)
def login(cred: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):

    user = db.query(User).filter(User.username == cred.username).first()
    if not user:
        user = db.query(User).filter(User.email == cred.username).first()
    
    if not user:
        password_manager.verify(cred.password, DUMMY_PASSWORD)
        raise HTTPException(detail="Invalid username or password", status_code=status.HTTP_401_UNAUTHORIZED)
    
    if not password_manager.verify(cred.password, user.password_hash):
        raise HTTPException(detail="Invalid username or password", status_code=status.HTTP_401_UNAUTHORIZED)
    
    payload = TokenPayload(
        sub=user.id,
    )
    
    access_token = oauth2.create_access_token(payload)
    refresh_token = oauth2.create_refresh_token(payload)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }

@router.post('/refresh', status_code=status.HTTP_200_OK)
def refresh(token: RefreshAccessTokenRequest):
    refresh_token = token.refresh_token
    access_token = oauth2.refresh_access_token(refresh_token)
    return {
        "access_token": access_token
    }
