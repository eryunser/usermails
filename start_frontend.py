#!/usr/bin/env python3
"""
用户邮箱系统前端服务器
端口: 8080
"""

import http.server
import socketserver
import os
from pathlib import Path
from api.utils.logger import logger

def main():
    """启动前端HTTP服务器"""
    logger.info("正在启动用户邮箱系统前端服务器...")
    logger.info("端口: 8080")
    logger.info("前端目录: web/")
    logger.info("访问地址: http://localhost:8080")
    logger.info("-" * 50)
    
    # 切换到项目根目录
    project_dir = Path(__file__).parent
    os.chdir(project_dir)
    
    # 设置前端目录
    frontend_dir = project_dir / "web"
    os.chdir(frontend_dir)
    
    # 端口
    PORT = 8080
    
    # 创建请求处理器，支持所有文件类型
    class CORSRequestHandler(http.server.SimpleHTTPRequestHandler):
        def end_headers(self):
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS, PUT, DELETE')
            self.send_header('Access-Control-Allow-Headers', '*')
            super().end_headers()
    
    # 启动服务器
    with socketserver.TCPServer(("", PORT), CORSRequestHandler) as httpd:
        logger.info(f"前端服务器运行在端口 {PORT}...")
        logger.info(f"访问地址: http://localhost:{PORT}/index.html")
        logger.info("按 Ctrl+C 停止服务器")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            logger.info("\n前端服务器已停止")
            httpd.shutdown()

if __name__ == "__main__":
    main()
