from pydantic import BaseModel, field_validator
from typing import Optional, List
from datetime import datetime
from enum import Enum

class EmailAccountBase(BaseModel):
    name: str
    email: str
    password: str
    imap_server: str
    imap_port: int = 993
    imap_ssl: bool = True
    smtp_server: str
    smtp_port: int = 465
    smtp_ssl: bool = True
    folder_sync_enabled: bool = True
    auto_sync_interval: int = 300

class EmailAccountCreate(EmailAccountBase):
    pass

class EmailAccountUpdate(BaseModel):
    name: Optional[str] = None
    password: Optional[str] = None
    imap_server: Optional[str] = None
    imap_port: Optional[int] = None
    imap_ssl: Optional[bool] = None
    smtp_server: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_ssl: Optional[bool] = None
    folder_sync_enabled: Optional[bool] = None
    auto_sync_interval: Optional[int] = None
    is_active: Optional[bool] = None

class EmailAccountResponse(EmailAccountBase):
    id: int
    user_id: int
    name: str
    is_active: bool
    is_verified: bool
    last_sync: Optional[datetime]
    sync_status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class EmailBase(BaseModel):
    subject: str
    sender: str
    recipients: str
    summary: Optional[str] = None
    folder: str = "INBOX"
    is_read: bool = False

class EmailResponse(EmailBase):
    id: int
    email_account_id: int
    uid: str
    message_id: Optional[str]
    cc: Optional[str] = None
    bcc: Optional[str] = None
    has_attachments: bool = False
    size: Optional[int] = None
    received_date: datetime
    sent_date: Optional[datetime] = None
    is_deleted: bool = False
    is_draft: bool = False
    created_at: datetime
    updated_at: datetime

    @field_validator('uid', mode='before')
    @classmethod
    def convert_uid_to_string(cls, v):
        """确保UID总是字符串格式"""
        if v is not None:
            return str(v)
        return v

    class Config:
        from_attributes = True

class EmailFilter(BaseModel):
    sender: Optional[str] = None
    subject: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    is_read: Optional[bool] = None
    has_attachments: Optional[bool] = None
    folder: Optional[str] = None

class EmailSendRequest(BaseModel):
    to: List[str]
    subject: str
    body: str
    cc: Optional[List[str]] = None
    bcc: Optional[List[str]] = None
    is_html: bool = False
    attachments: Optional[List[str]] = None

class EmailSyncRequest(BaseModel):
    folders: List[str] = ["INBOX", "Sent", "Drafts", "Trash"]
    sync_since: Optional[datetime] = None
    full_sync: bool = False

class EmailFolder(BaseModel):
    name: str
    total_count: int
    unread_count: int
    sync_enabled: bool = True

class EmailSearchRequest(BaseModel):
    query: str
    folder: Optional[str] = "INBOX"
    limit: int = 50
    offset: int = 0
