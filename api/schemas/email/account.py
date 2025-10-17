from pydantic import BaseModel
from typing import Optional

class EmailAccountBase(BaseModel):
    name: str
    email: str
    imap_server: str
    imap_port: int = 993
    imap_ssl: bool = True
    smtp_server: str
    smtp_port: int = 465
    smtp_ssl: bool = True

class EmailAccountCreate(EmailAccountBase):
    password: str

class EmailAccountUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    imap_server: Optional[str] = None
    imap_port: Optional[int] = None
    imap_ssl: Optional[bool] = None
    smtp_server: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_ssl: Optional[bool] = None

class EmailAccount(EmailAccountBase):
    id: int
    user_id: int
    is_active: bool
    is_verified: bool

    class Config:
        from_attributes = True
