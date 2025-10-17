from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from api.database import Base

class User(Base):
    """
    用户模型
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    mfa_secret = Column(String, nullable=True)
    is_mfa_enabled = Column(Boolean, default=False)
    avatar = Column(String, nullable=True)
    delete_time = Column(DateTime, nullable=True)

    email_accounts = relationship("EmailAccount", back_populates="user")
