from fastapi import FastAPI, Depends, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from api.database import engine, Base, SessionLocal
# 导入所有模型以确保 SQLAlchemy 能识别它们
from api.model import User, EmailAccount, Email, Draft
from api.controller import users, auth, ws, email_accounts, emails, drafts
from api.utils.response import fail
from api.utils.logger import get_logger
from api.utils.jwt_middleware import JWTRefreshMiddleware
from api.utils.admin_init import init_admin_account
import uvicorn
import os

# 初始化日志
logger = get_logger("main")

# 从环境变量读取配置（Docker会注入）
APP_NAME = os.getenv("APP_NAME", "用户邮箱系统")
SECRET_KEY = os.getenv("SECRET_KEY", "your-super-secret-key-change-this-in-production")

# 确保上传目录存在
if not os.path.exists("web/uploads"):
    os.makedirs("web/uploads", exist_ok=True)

# 确保数据目录存在
if not os.path.exists("data"):
    os.makedirs("data", exist_ok=True)

# 创建数据库表
Base.metadata.create_all(bind=engine)

# 初始化管理员账号（仅在Docker环境下生效）
try:
    db = SessionLocal()
    init_admin_account(db)
    db.close()
except Exception as e:
    logger.error(f"管理员账号初始化失败: {e}")

# 创建FastAPI应用
app = FastAPI(
    title=APP_NAME,
    description="多用户在线邮箱客户端服务API",
    version="1.0.0",
    root_path="/api"
)

# Pydantic验证错误处理器
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    处理请求参数验证错误，返回统一格式
    """
    errors = exc.errors()
    if errors:
        # 提取第一个错误的详细信息
        first_error = errors[0]
        msg = first_error.get("msg", "验证失败")
        
        # 如果是自定义错误消息，直接使用
        if "Value error" in msg:
            msg = msg.replace("Value error, ", "")
        
        error_msg = msg
        logger.warning(f"请求验证失败: {error_msg}")
    else:
        error_msg = "请求参数验证失败"
        logger.warning(f"请求验证失败: {exc}")
    
    return JSONResponse(
        status_code=200,
        content=fail(msg=error_msg)
    )

# 全局异常处理器
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # 对于所有未被特定异常处理器捕获的异常，都返回一个通用的JSON错误响应。
    # 这有助于防止敏感的服务器信息（如堆栈跟踪）泄露给客户端。
    logger.error(f"全局异常: {exc}", exc_info=True)
    return JSONResponse(
        status_code=200,
        content=fail(msg=f"服务器内部错误，请联系管理员")
    )

# 配置CORS - 允许所有来源
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-New-Token"],  # 允许前端访问X-New-Token响应头
)

# 添加JWT自动续期中间件
app.add_middleware(JWTRefreshMiddleware)

# 挂载静态文件目录
app.mount("/uploads", StaticFiles(directory="web/uploads"), name="uploads")

# 注册路由
app.include_router(auth.router, prefix="/auth", tags=["authentication"])
app.include_router(users.router, prefix="/users", tags=["users"])
app.include_router(email_accounts.router, prefix="/email-accounts", tags=["email-accounts"])
app.include_router(emails.router, prefix="/email-accounts/{account_id}/emails", tags=["emails"])
app.include_router(drafts.router, prefix="/email-accounts/{account_id}/drafts", tags=["drafts"])
app.include_router(ws.router, prefix="", tags=["websockets"])

@app.get("/")
async def root():
    return {"message": f"欢迎使用 {APP_NAME}"}

@app.get("/health")
async def health_check():
    return {"status": "正常", "service": APP_NAME}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9999, reload=False)
