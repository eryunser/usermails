#!/usr/bin/env python3
"""
用户邮箱系统启动脚本
端口: 999 (固定调试端口)
自动重载: 开启
"""

import subprocess
import sys
import os
from pathlib import Path
from api.utils.logger import logger

def main():
    """启动FastAPI服务器"""
    logger.info("正在启动用户邮箱系统服务器...")
    logger.info("端口: 9999")
    logger.info("自动重载: 已开启")
    logger.info("-" * 50)
    
    # 设置工作目录为项目根目录，而不是api目录
    project_dir = Path(__file__).parent
    os.chdir(project_dir)
    
    # 设置PYTHONPATH以允许绝对导入
    env = os.environ.copy()
    env['PYTHONPATH'] = str(project_dir) + os.pathsep + env.get('PYTHONPATH', '')
    
    # 启动uvicorn服务器，使用绝对模块路径
    cmd = [
        sys.executable, "-m", "uvicorn", 
        "api.main:app", 
        "--host", "0.0.0.0", 
        "--port", "9999", 
        "--reload",
        "--reload-dir", str(project_dir / "api")
    ]
    
    try:
        subprocess.run(cmd, check=True, env=env)
    except subprocess.CalledProcessError as e:
        logger.error(f"服务器启动失败: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("\n服务器已停止")
        sys.exit(0)

if __name__ == "__main__":
    main()
