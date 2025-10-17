"""
数据库初始化工具
用于初次部署时自动创建数据库表结构
"""
import os
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from api.database import engine, Base
from api.model.user import User
from api.model.email_account import EmailAccount
from api.model.email import Email
from api.model.draft import Draft
from api.utils.logger import get_logger

logger = get_logger("init_db")


def init_database():
    """初始化数据库，创建所有表"""
    try:
        logger.info("开始初始化数据库...")
        
        # 检查数据库文件是否已存在
        db_path = "usermails.db"
        if os.path.exists(db_path):
            logger.warning(f"数据库文件 {db_path} 已存在")
            response = input("是否要重新创建数据库？这将删除所有现有数据！(yes/no): ")
            if response.lower() != 'yes':
                logger.info("取消数据库初始化")
                return
            os.remove(db_path)
            logger.info(f"已删除旧数据库文件: {db_path}")
        
        # 创建所有表
        Base.metadata.create_all(bind=engine)
        logger.info("数据库表创建成功！")
        
        # 打印创建的表信息
        tables = Base.metadata.tables.keys()
        logger.info(f"已创建 {len(tables)} 个表:")
        for table_name in tables:
            logger.info(f"  - {table_name}")
        
        logger.info("数据库初始化完成！")
        
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}", exc_info=True)
        raise


def check_database():
    """检查数据库连接和表结构"""
    try:
        logger.info("检查数据库连接...")
        
        # 获取所有表名
        from sqlalchemy import inspect
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        if not tables:
            logger.warning("数据库中没有表，请先运行初始化")
            return False
        
        logger.info(f"数据库连接正常，共有 {len(tables)} 个表:")
        for table_name in tables:
            columns = inspector.get_columns(table_name)
            logger.info(f"  - {table_name} ({len(columns)} 个字段)")
        
        return True
        
    except Exception as e:
        logger.error(f"数据库检查失败: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="数据库初始化工具")
    parser.add_argument(
        "action",
        choices=["init", "check"],
        help="操作: init=初始化数据库, check=检查数据库"
    )
    
    args = parser.parse_args()
    
    if args.action == "init":
        init_database()
    elif args.action == "check":
        check_database()
