"""
管理员账号初始化工具
用于Docker部署时自动创建或重置管理员账号
"""
import os
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from api.model.user import User
from api.utils.logger import get_logger

logger = get_logger("admin_init")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_password_hash(password: str) -> str:
    """生成密码哈希"""
    return pwd_context.hash(password)


def init_admin_account(db: Session):
    """
    初始化管理员账号
    
    环境变量：
    - ADMIN_ACCOUNT: 管理员账号（用户名）
    - ADMIN_PASSWORD: 管理员密码
    - RESET_ADMIN_PASSWORD: 是否强制重置管理员密码
    """
    try:
        # 读取环境变量
        admin_account = os.getenv("ADMIN_ACCOUNT", "").strip()
        admin_password = os.getenv("ADMIN_PASSWORD", "").strip()
        reset_password = os.getenv("RESET_ADMIN_PASSWORD", "").strip()
        
        # 检查是否需要重置密码
        if reset_password:
            logger.info("检测到 RESET_ADMIN_PASSWORD 环境变量，准备重置管理员密码...")
            reset_admin_password(db, reset_password)
            return
        
        # 检查是否设置了初始管理员账号配置
        if not admin_account or not admin_password:
            logger.info("未设置 ADMIN_ACCOUNT 或 ADMIN_PASSWORD 环境变量，跳过管理员账号初始化")
            return
        
        # 检查管理员账号是否已存在
        existing_admin = db.query(User).filter(
            User.username == admin_account
        ).first()
        
        if existing_admin:
            logger.info(f"管理员账号 '{admin_account}' 已存在，跳过创建")
            return
        
        # 创建管理员账号
        admin_email = f"{admin_account}@example.com"
        hashed_password = get_password_hash(admin_password)
        
        admin_user = User(
            username=admin_account,
            email=admin_email,
            hashed_password=hashed_password,
            full_name="系统管理员",
            is_active=True,
            is_admin=True,
        )
        
        db.add(admin_user)
        db.commit()
        db.refresh(admin_user)
        
        logger.info(f"✅ 成功创建管理员账号: {admin_account}")
        logger.info(f"   用户名: {admin_account}")
        logger.info(f"   邮箱: {admin_email}")
        logger.info("   请妥善保管管理员密码！")
        
    except Exception as e:
        logger.error(f"初始化管理员账号失败: {e}", exc_info=True)
        db.rollback()
        raise


def reset_admin_password(db: Session, new_password: str):
    """
    重置管理员密码
    
    查找第一个管理员账号并重置其密码
    """
    try:
        # 查找第一个管理员账号
        admin_user = db.query(User).filter(
            User.is_admin == True
        ).first()
        
        if not admin_user:
            logger.warning("未找到管理员账号，无法重置密码")
            return
        
        # 重置密码
        hashed_password = get_password_hash(new_password)
        admin_user.hashed_password = hashed_password
        db.commit()
        
        logger.info(f"✅ 成功重置管理员账号 '{admin_user.username}' 的密码")
        logger.warning("   请立即修改 RESET_ADMIN_PASSWORD 环境变量，避免每次启动都重置密码！")
        
    except Exception as e:
        logger.error(f"重置管理员密码失败: {e}", exc_info=True)
        db.rollback()
        raise
