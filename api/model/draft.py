from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from api.database import Base

class Draft(Base):
    __tablename__ = 'drafts'

    id = Column(Integer, primary_key=True, index=True)
    email_account_id = Column(Integer, ForeignKey('email_accounts.id', ondelete='CASCADE'), nullable=False)
    
    subject = Column(String, default="无主题")
    recipients = Column(Text)
    cc = Column(Text)
    bcc = Column(Text)
    body = Column(Text)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    account = relationship("EmailAccount")
