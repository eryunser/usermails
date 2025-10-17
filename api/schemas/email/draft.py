from pydantic import BaseModel
from typing import Optional

class EmailDraft(BaseModel):
    id: Optional[int] = None
    subject: Optional[str] = None
    recipients: Optional[str] = None
    cc: Optional[str] = None
    bcc: Optional[str] = None
    body: Optional[str] = None

class EmailDraftResponse(BaseModel):
    id: int

    class Config:
        from_attributes = True
