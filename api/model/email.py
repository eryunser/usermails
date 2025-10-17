from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from api.database import Base

class Email(Base):
    """
    邮件模型
    """
    __tablename__ = "emails"
    __table_args__ = (
        # 内容约束：同一账号下内容相同的邮件必须来自相同IMAP位置
        UniqueConstraint(
            'email_account_id',
            'message_id',
            'content_hash',
            'folder',
            'uid',
            name='uq_content_location'
        ),
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    email_account_id = Column(Integer, ForeignKey("email_accounts.id"), nullable=False)  # 外键关联邮箱账户
    uid = Column(String, nullable=False)  # 邮件唯一标识符（仅在同一文件夹+UIDVALIDITY下有效）
    uidvalidity = Column(String, nullable=True)  # 文件夹的UIDVALIDITY值，用于跟踪文件夹版本
    message_id = Column(String, nullable=True, index=True)  # 邮件消息ID（全局唯一标识符）
    email_hash = Column(String, nullable=True, index=True)  # 基于邮件元数据生成的哈希值（用于无Message-ID的邮件）
    is_generated_message_id = Column(Boolean, default=False)  # 标记Message-ID是否由系统生成
    
    # 三层唯一性保障体系新增字段
    content_hash = Column(String(64), nullable=True, index=True)  # 完整SHA256内容哈希
    imap_key = Column(String(128), nullable=True, index=True)  # IMAP位置标识: folder|uid|uidvalidity
    
    # 邮件基本信息
    subject = Column(String, nullable=False)
    sender = Column(String, nullable=False)  # 发件人
    recipients = Column(String, nullable=False)  # 收件人（可能多个，用分隔符分隔）
    cc = Column(String, nullable=True)  # 抄送
    bcc = Column(String, nullable=True)  # 密送
    
    # 邮件内容
    summary = Column(String(255), nullable=True)  # 邮件摘要
    has_attachments = Column(Boolean, default=False)
    
    # 邮件元数据
    folder = Column(String, default="INBOX")  # 邮件文件夹
    size = Column(Integer, nullable=True)  # 邮件大小（字节）
    received_date = Column(DateTime, nullable=False)  # 接收时间
    sent_date = Column(DateTime, nullable=True)  # 发送时间
    
    # 邮件状态
    is_read = Column(Boolean, default=False)
    is_deleted = Column(Boolean, default=False)
    
    eml_path = Column(String, nullable=True)  # EML文件存储路径
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    account = relationship("EmailAccount", back_populates="emails")
