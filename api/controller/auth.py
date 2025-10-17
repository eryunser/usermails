from fastapi import APIRouter, Depends, status, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Optional
from jose import jwt
import bcrypt
import os
from api.database import get_db
from api.model.user import User
from api.schemas.auth import Token, TokenData, UserCreate, UserResponse, UserLogin, VerifyPasswordRequest
from api.utils.response import success, fail
import pyotp

router = APIRouter()

# JWT配置 - 从环境变量读取
SECRET_KEY = os.getenv("SECRET_KEY", "your-super-secret-key-change-this-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440  # 24小时

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def authenticate_user(db: Session, username: str, password: str):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无法验证凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except jwt.JWTError:
        raise credentials_exception
    user = db.query(User).filter(User.username == token_data.username).first()
    if user is None:
        raise credentials_exception
    return user

def get_current_user_from_token(token: str, db: Session):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
        token_data = TokenData(username=username)
    except jwt.JWTError:
        return None
    user = db.query(User).filter(User.username == token_data.username).first()
    return user

@router.post("/register")
async def register(user: UserCreate, db: Session = Depends(get_db)):
    try:
        db_user = db.query(User).filter(User.username == user.username).first()
        if db_user:
            return fail("用户名已存在")
        
        is_first_user = db.query(User).count() == 0
        hashed_password = get_password_hash(user.password)
        db_user = User(
            username=user.username,
            email=f"{user.username}@example.com",
            hashed_password=hashed_password,
            is_admin=is_first_user
        )
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        return success(UserResponse.from_orm(db_user), msg="注册成功")
    except Exception as e:
        db.rollback()
        return fail(f"注册失败: {str(e)}")

@router.post("/login")
async def login(form_data: UserLogin, db: Session = Depends(get_db)):
    try:
        user = authenticate_user(db, form_data.username, form_data.password)
        if not user:
            return fail("用户名或密码错误")
        
        # 检查账号是否被禁用或删除
        if not user.is_active:
            return fail("账号已被禁用")
        
        if user.delete_time is not None:
            return fail("账号已被删除")

        if user.is_mfa_enabled:
            if not form_data.mfa_token:
                # 当需要MFA但未提供时，返回自定义错误信息
                return fail("需要MFA令牌", data={"mfa_required": True})
            
            totp = pyotp.TOTP(user.mfa_secret)
            if not totp.verify(form_data.mfa_token):
                return fail("无效的MFA令牌")

        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": user.username}, expires_delta=access_token_expires
        )
        token_data = {"access_token": access_token, "token_type": "bearer"}
        return success(token_data, msg="登录成功")
    except Exception as e:
        return fail(f"登录失败: {str(e)}")

@router.post("/logout")
async def logout():
    return success(msg="已成功退出登录")

@router.get("/me")
async def read_users_me(current_user: User = Depends(get_current_user)):
    try:
        user_data = UserResponse.from_orm(current_user)
        return success(user_data)
    except Exception as e:
        return fail(f"获取用户信息失败: {str(e)}")

@router.post("/verify-password")
async def verify_current_password(
    request: VerifyPasswordRequest,
    current_user: User = Depends(get_current_user)
):
    try:
        if not verify_password(request.password, current_user.hashed_password):
            return fail("密码不正确")
        return success(msg="密码验证成功")
    except Exception as e:
        return fail(f"密码验证失败: {str(e)}")
