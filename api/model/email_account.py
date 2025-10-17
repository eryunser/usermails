from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from api.database import Base

class EmailAccount(Base):
    """
    邮箱账户模型
    """
    __tablename__ = "email_accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # 外键关联用户
    display_order = Column(Integer, default=0)  # 显示顺序
    name = Column(String, nullable=False)  # 邮箱名称
    email = Column(String, unique=True, index=True, nullable=False)  # 邮箱地址
    password = Column(String, nullable=False)  # 邮箱密码（加密存储）
    
    # IMAP配置
    imap_server = Column(String, nullable=False)
    imap_port = Column(Integer, default=993)  # 默认IMAP SSL端口
    imap_ssl = Column(Boolean, default=True)
    
    # SMTP配置
    smtp_server = Column(String, nullable=False)
    smtp_port = Column(Integer, default=465)  # 默认SMTP SSL端口
    smtp_ssl = Column(Boolean, default=True)
    
    # 邮箱状态
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)  # 邮箱验证状态
    last_sync = Column(DateTime, nullable=True)  # 最后同步时间
    sync_status = Column(String, default="idle")  # 同步状态
    
    # 邮箱配置
    folder_sync_enabled = Column(Boolean, default=True)  # 文件夹同步开关
    auto_sync_interval = Column(Integer, default=300)  # 自动同步间隔（秒）
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="email_accounts")
    emails = relationship("Email", back_populates="account", cascade="all, delete-orphan")
