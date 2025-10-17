from fastapi import APIRouter, Depends, status, File, UploadFile
from sqlalchemy.orm import Session
from typing import List
import pyotp
import os
import shutil
from datetime import datetime
import qrcode
import io
import base64
from api.database import get_db
from api.model.user import User
from api.schemas.auth import UserResponse, UserUpdate, ChangePassword, MFASetupResponse, MFAEnableRequest, MFADisableRequest, MFAVerifyRequest, AdminUserUpdate
from api.controller.auth import get_current_user, get_password_hash, verify_password, SECRET_KEY, ALGORITHM
from jose import jwt
import secrets
import string
from api.utils.response import success, fail

router = APIRouter()
 
@router.get("/")
async def get_users(
    username: str = None,
    email: str = None,
    is_active: bool = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取用户列表（需要管理员权限）
    支持筛选条件：用户名、邮箱、状态
    """
    try:
        if not current_user.is_admin:
            return fail("权限不足")
        
        # 构建查询
        query = db.query(User).filter(User.delete_time.is_(None))
        
        # 添加筛选条件
        if username:
            query = query.filter(User.username.like(f"%{username}%"))
        if email:
            query = query.filter(User.email.like(f"%{email}%"))
        if is_active is not None:
            query = query.filter(User.is_active == is_active)
        
        users = query.all()
        count = len(users)
        return success(users, count=count)
    except Exception as e:
        return fail(f"获取用户列表失败: {str(e)}")

@router.get("/{user_id}")
async def get_user(
    user_id: int, 
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取指定用户信息
    """
    try:
        if not current_user.is_admin and current_user.id != user_id:
            return fail("权限不足")
            
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return fail("用户未找到")
        
        return success(user)
    except Exception as e:
        return fail(f"获取用户信息失败: {str(e)}")

@router.post("/me/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    上传头像
    """
    try:
        # 验证文件类型和大小
        if file.content_type not in ["image/jpeg", "image/png", "image/gif"]:
            return fail("只支持上传 JPG, PNG, GIF 格式的图片")
        
        # 限制大小为 2MB
        if file.size > 2 * 1024 * 1024:
            return fail("图片大小不能超过 2MB")

        upload_dir = "web/uploads/avatars"
        os.makedirs(upload_dir, exist_ok=True)
        
        # 生成唯一文件名
        file_extension = os.path.splitext(file.filename)[1]
        unique_filename = f"{current_user.id}_{datetime.now().strftime('%Y%m%d%H%M%S')}{file_extension}"
        file_path = os.path.join(upload_dir, unique_filename)
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # 更新用户头像URL为相对路径
        avatar_url = f"/uploads/avatars/{unique_filename}"
        current_user.avatar = avatar_url
        db.commit()
        db.refresh(current_user)
            
        return success(data={"avatar_url": avatar_url})
    except Exception as e:
        db.rollback()
        return fail(f"上传头像失败: {str(e)}")

@router.put("/me")
async def update_user_me(
    user_update: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    更新当前用户信息
    """
    try:
        if user_update.email:
            existing_user = db.query(User).filter(
                User.email == user_update.email,
                User.id != current_user.id
            ).first()
            if existing_user:
                return fail("该邮箱已被注册")
        
        current_user.full_name = user_update.full_name or current_user.full_name
        current_user.email = user_update.email or current_user.email
        
        if user_update.password:
            if current_user.is_mfa_enabled:
                if not user_update.mfa_token:
                    return fail("请输入MFA代码")
                totp = pyotp.TOTP(current_user.mfa_secret)
                if not totp.verify(user_update.mfa_token):
                    return fail("无效的MFA代码")
            current_user.hashed_password = get_password_hash(user_update.password)

        db.commit()
        db.refresh(current_user)
        return success(current_user, msg="用户信息更新成功")
    except Exception as e:
        db.rollback()
        return fail(f"更新用户信息失败: {str(e)}")

@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    删除用户（需要管理员权限）
    """
    try:
        if not current_user.is_admin:
            return fail("权限不足")
        
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return fail("用户未找到")
        
        if user.id == current_user.id:
            return fail("不能删除自己")
        
        db.delete(user)
        db.commit()
        return success(msg="用户删除成功")
    except Exception as e:
        db.rollback()
        return fail(f"删除用户失败: {str(e)}")

@router.post("/me/mfa/generate")
async def generate_mfa_secret(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    生成MFA密钥和二维码
    """
    try:
        if current_user.is_mfa_enabled:
            return fail("MFA已启用")

        secret = pyotp.random_base32()
        current_user.mfa_secret = secret
        db.commit()

        totp = pyotp.TOTP(secret)
        provisioning_uri = totp.provisioning_uri(name=current_user.username, issuer_name="UserMails")
        
        img = qrcode.make(provisioning_uri)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        qr_code_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        return success({"secret": secret, "qr_code": f"data:image/png;base64,{qr_code_b64}"})
    except Exception as e:
        db.rollback()
        return fail(f"生成MFA密钥失败: {str(e)}")

@router.post("/me/mfa/enable")
async def enable_mfa(
    request: MFAEnableRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    启用MFA
    """
    try:
        if current_user.is_mfa_enabled:
            return fail("MFA已启用")
        
        if not current_user.mfa_secret:
            return fail("请先生成MFA密钥")

        totp = pyotp.TOTP(current_user.mfa_secret)
        if not totp.verify(request.token):
            return fail("无效的MFA令牌")

        current_user.is_mfa_enabled = True
        db.commit()
        return success(msg="MFA启用成功")
    except Exception as e:
        db.rollback()
        return fail(f"启用MFA失败: {str(e)}")

@router.post("/me/mfa/verify")
async def verify_mfa(
    request: MFAVerifyRequest,
    current_user: User = Depends(get_current_user)
):
    """
    验证MFA代码
    """
    try:
        if not current_user.is_mfa_enabled or not current_user.mfa_secret:
            return fail("MFA未启用")

        totp = pyotp.TOTP(current_user.mfa_secret)
        if not totp.verify(request.token):
            return fail("无效的MFA代码")
        
        return success(msg="MFA代码验证成功")
    except Exception as e:
        return fail(f"验证MFA代码失败: {str(e)}")

@router.post("/me/mfa/disable")
async def disable_mfa(
    request: MFADisableRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    禁用MFA
    """
    try:
        if not current_user.is_mfa_enabled:
            return fail("MFA未启用")

        totp = pyotp.TOTP(current_user.mfa_secret)
        if not totp.verify(request.token):
            return fail("无效的MFA代码")

        current_user.is_mfa_enabled = False
        current_user.mfa_secret = None
        db.commit()
        return success(msg="MFA禁用成功")
    except Exception as e:
        db.rollback()
        return fail(f"禁用MFA失败: {str(e)}")

# ==================== 管理员用户管理接口 ====================

def generate_random_password(length=12):
    """生成随机密码"""
    characters = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(characters) for _ in range(length))

def invalidate_user_tokens(user_id: int, db: Session):
    """使用户的所有token失效（通过更新updated_at时间戳）"""
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.updated_at = datetime.now()
        db.commit()

@router.put("/admin/{user_id}")
async def admin_update_user(
    user_id: int,
    user_update: AdminUserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    管理员修改用户基本信息
    """
    try:
        if not current_user.is_admin:
            return fail("权限不足")
        
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return fail("用户未找到")
        
        # 检查username是否重复（排除已删除的用户）
        if user_update.username and user_update.username != user.username:
            existing = db.query(User).filter(
                User.username == user_update.username,
                User.delete_time.is_(None)
            ).first()
            if existing:
                return fail("用户名已存在")
            user.username = user_update.username
        
        # 检查email是否重复（排除已删除的用户）
        if user_update.email and user_update.email != user.email:
            existing = db.query(User).filter(
                User.email == user_update.email,
                User.delete_time.is_(None)
            ).first()
            if existing:
                return fail("邮箱已存在")
            user.email = user_update.email
        
        if user_update.full_name is not None:
            user.full_name = user_update.full_name
        
        if user_update.password:
            user.hashed_password = get_password_hash(user_update.password)
        
        db.commit()
        db.refresh(user)
        return success(user, msg="用户信息更新成功")
    except Exception as e:
        db.rollback()
        return fail(f"更新用户信息失败: {str(e)}")

@router.post("/admin/{user_id}/cancel-mfa")
async def admin_cancel_mfa(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    管理员取消用户MFA
    """
    try:
        if not current_user.is_admin:
            return fail("权限不足")
        
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return fail("用户未找到")
        
        if not user.is_mfa_enabled:
            return fail("该用户未启用MFA")
        
        user.is_mfa_enabled = False
        user.mfa_secret = None
        db.commit()
        return success(msg="MFA已取消")
    except Exception as e:
        db.rollback()
        return fail(f"取消MFA失败: {str(e)}")

@router.post("/admin/{user_id}/toggle-status")
async def admin_toggle_user_status(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    管理员启用/禁用用户账号
    """
    try:
        if not current_user.is_admin:
            return fail("权限不足")
        
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return fail("用户未找到")
        
        if user.id == current_user.id:
            return fail("不能禁用自己的账号")
        
        # 切换状态
        user.is_active = not user.is_active
        
        # 如果禁用账号，则使该用户的所有token失效
        if not user.is_active:
            invalidate_user_tokens(user_id, db)
        
        db.commit()
        status_text = "启用" if user.is_active else "禁用"
        return success({"is_active": user.is_active}, msg=f"账号已{status_text}")
    except Exception as e:
        db.rollback()
        return fail(f"切换账号状态失败: {str(e)}")

@router.delete("/admin/{user_id}")
async def admin_delete_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    管理员删除用户（伪删除）
    """
    try:
        if not current_user.is_admin:
            return fail("权限不足")
        
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return fail("用户未找到")
        
        if user.id == current_user.id:
            return fail("不能删除自己")
        
        # 伪删除
        user.delete_time = datetime.now()
        user.is_active = False
        
        # 使该用户的所有token失效
        invalidate_user_tokens(user_id, db)
        
        db.commit()
        return success(msg="用户已删除")
    except Exception as e:
        db.rollback()
        return fail(f"删除用户失败: {str(e)}")

@router.post("/admin/create")
async def admin_create_user(
    user_data: AdminUserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    管理员创建新用户
    """
    try:
        if not current_user.is_admin:
            return fail("权限不足")
        
        # 检查必填字段
        if not user_data.username or not user_data.email or not user_data.password:
            return fail("用户名、邮箱和密码为必填项")
        
        # 检查用户名是否已存在（排除已删除的用户）
        existing_username = db.query(User).filter(
            User.username == user_data.username,
            User.delete_time.is_(None)
        ).first()
        if existing_username:
            return fail("用户名已存在")
        
        # 检查邮箱是否已存在（排除已删除的用户）
        existing_email = db.query(User).filter(
            User.email == user_data.email,
            User.delete_time.is_(None)
        ).first()
        if existing_email:
            return fail("邮箱已存在")
        
        # 创建新用户
        new_user = User(
            username=user_data.username,
            email=user_data.email,
            full_name=user_data.full_name or "",
            hashed_password=get_password_hash(user_data.password),
            is_active=True,
            is_admin=False
        )
        
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        return success(new_user, msg="用户创建成功")
    except Exception as e:
        db.rollback()
        return fail(f"创建用户失败: {str(e)}")

@router.get("/admin/generate-password")
async def admin_generate_password(
    current_user: User = Depends(get_current_user)
):
    """
    生成随机密码
    """
    try:
        if not current_user.is_admin:
            return fail("权限不足")
        
        password = generate_random_password(12)
        return success({"password": password})
    except Exception as e:
        return fail(f"生成随机密码失败: {str(e)}")
