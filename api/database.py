from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

# SQLite数据库配置
DATABASE_URL = "sqlite:///./data/usermails.db"

# 创建数据库引擎
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 15}  # SQLite特定配置, 增加超时时间
)

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 基础模型类
Base = declarative_base()

def get_db():
    """
    获取数据库会话的依赖函数
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
