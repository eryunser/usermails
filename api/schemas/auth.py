from pydantic import BaseModel, field_validator, Field
from typing import Optional
from datetime import datetime
import re

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    
    @field_validator('username')
    @classmethod
    def validate_username(cls, v):
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError('用户名只能包含字母、数字、下划线和横线')
        return v

class UserCreate(UserBase):
    password: str = Field(..., min_length=8, max_length=128)
    email: str
    full_name: Optional[str] = Field(None, max_length=100)
    
    @field_validator('email')
    @classmethod
    def validate_email(cls, v):
        if not v:
            raise ValueError('邮箱不能为空')
        # 基本的邮箱格式验证，允许本地域名
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$|^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.local$', v):
            raise ValueError('邮箱格式不正确')
        return v
    
    @field_validator('password')
    @classmethod
    def validate_password(cls, v):
        if not re.search(r'[A-Z]', v):
            raise ValueError('密码必须包含至少一个大写字母')
        if not re.search(r'[a-z]', v):
            raise ValueError('密码必须包含至少一个小写字母')
        if not re.search(r'[0-9]', v):
            raise ValueError('密码必须包含至少一个数字')
        if not re.search(r'[!@#$%^&*(),.?":{}|<>_\-+=\[\]\\\/;`~]', v):
            raise ValueError('密码必须包含至少一个特殊字符')
        return v

class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(None, max_length=100)
    email: Optional[str] = None
    password: Optional[str] = Field(None, min_length=8, max_length=128)
    mfa_token: Optional[str] = None
    
    @field_validator('email')
    @classmethod
    def validate_email(cls, v):
        if v is None:
            return v
        # 基本的邮箱格式验证，允许本地域名
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$|^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.local$', v):
            raise ValueError('邮箱格式不正确')
        return v
    
    @field_validator('password')
    @classmethod
    def validate_password(cls, v):
        if v is None:
            return v
        if not re.search(r'[A-Z]', v):
            raise ValueError('密码必须包含至少一个大写字母')
        if not re.search(r'[a-z]', v):
            raise ValueError('密码必须包含至少一个小写字母')
        if not re.search(r'[0-9]', v):
            raise ValueError('密码必须包含至少一个数字')
        if not re.search(r'[!@#$%^&*(),.?":{}|<>_\-+=\[\]\\\/;`~]', v):
            raise ValueError('密码必须包含至少一个特殊字符')
        return v

class UserResponse(UserBase):
    id: int
    is_active: bool
    is_admin: bool
    is_mfa_enabled: bool
    created_at: datetime
    updated_at: datetime
    full_name: Optional[str] = None
    email: Optional[str] = None
    avatar: Optional[str] = None

    class Config:
        from_attributes = True

class UserLogin(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    mfa_token: Optional[str] = None

class ChangePassword(BaseModel):
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=128)
    
    @field_validator('new_password')
    @classmethod
    def validate_new_password(cls, v):
        if not re.search(r'[A-Z]', v):
            raise ValueError('密码必须包含至少一个大写字母')
        if not re.search(r'[a-z]', v):
            raise ValueError('密码必须包含至少一个小写字母')
        if not re.search(r'[0-9]', v):
            raise ValueError('密码必须包含至少一个数字')
        if not re.search(r'[!@#$%^&*(),.?":{}|<>_\-+=\[\]\\\/;`~]', v):
            raise ValueError('密码必须包含至少一个特殊字符')
        return v

class MFASetupResponse(BaseModel):
    secret: str
    qr_code: str

class MFAEnableRequest(BaseModel):
    token: str

class MFAVerifyRequest(BaseModel):
    token: str

class MFADisableRequest(BaseModel):
    token: str

class VerifyPasswordRequest(BaseModel):
    password: str

class AdminUserUpdate(BaseModel):
    full_name: Optional[str] = Field(None, max_length=100)
    email: Optional[str] = None
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    password: Optional[str] = Field(None, min_length=8, max_length=128)
    
    @field_validator('email')
    @classmethod
    def validate_email(cls, v):
        if v is None:
            return v
        # 基本的邮箱格式验证，允许本地域名
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$|^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.local$', v):
            raise ValueError('邮箱格式不正确')
        return v
    
    @field_validator('username')
    @classmethod
    def validate_username(cls, v):
        if v is None:
            return v
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError('用户名只能包含字母、数字、下划线和横线')
        return v
    
    @field_validator('password')
    @classmethod
    def validate_password(cls, v):
        if v is None:
            return v
        if not re.search(r'[A-Z]', v):
            raise ValueError('密码必须包含至少一个大写字母')
        if not re.search(r'[a-z]', v):
            raise ValueError('密码必须包含至少一个小写字母')
        if not re.search(r'[0-9]', v):
            raise ValueError('密码必须包含至少一个数字')
        if not re.search(r'[!@#$%^&*(),.?":{}|<>_\-+=\[\]\\\/;`~]', v):
            raise ValueError('密码必须包含至少一个特殊字符')
        return v
