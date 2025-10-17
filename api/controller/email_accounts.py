import asyncio
import os
import re
import imaplib
import smtplib
import ssl
from fastapi import APIRouter, Depends, Query, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel
from datetime import datetime

from api.database import get_db
from api.model.user import User
from api.model.email_account import EmailAccount
from api.controller.auth import get_current_user
from api.schemas.email.account import EmailAccount as EmailAccountResponse, EmailAccountCreate, EmailAccountUpdate
from api.utils.response import success, fail
from api.service.email_service import EmailService
from api.utils.helpers import decode_modified_utf7, encode_modified_utf7
from api.utils.cache import cache
from api.utils.logger import get_logger

# 初始化日志
logger = get_logger("email_accounts")

# 用于验证的模型，password是可选的，以便在更新时处理
class EmailAccountValidate(BaseModel):
    name: str
    email: str
    imap_server: str
    imap_port: int = 993
    imap_ssl: bool = True
    smtp_server: str
    smtp_port: int = 465
    smtp_ssl: bool = True
    password: Optional[str] = None

class AccountOrderUpdate(BaseModel):
    account_ids: list[int]

class FolderCreate(BaseModel):
    folder_name: str
    parent_folder: Optional[str] = None

class FolderRename(BaseModel):
    old_dir: str
    new_dir: str

class FolderDelete(BaseModel):
    folder_name: str

router = APIRouter()

@router.get("")
async def get_email_accounts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取当前用户的邮箱账户列表
    """
    accounts = db.query(EmailAccount).filter(
        EmailAccount.user_id == current_user.id
    ).order_by(EmailAccount.display_order).all()
    
    # 显式转换为 Pydantic 模型列表以避免序列化问题
    response_accounts = [EmailAccountResponse.from_orm(acc) for acc in accounts]
    return success(response_accounts)

@router.post("")
async def create_email_account(
    account: EmailAccountCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    创建邮箱账户
    """
    # 检查邮箱是否已存在
    existing_account = db.query(EmailAccount).filter(
        EmailAccount.email == account.email,
        EmailAccount.user_id == current_user.id
    ).first()
    if existing_account:
        return fail("该邮箱账户已存在")
    
    db_account = EmailAccount(
        user_id=current_user.id,
        name=account.name,
        email=account.email,
        password=account.password,  # 在实际应用中，这里应该是加密后的密码
        imap_server=account.imap_server,
        imap_port=account.imap_port,
        imap_ssl=account.imap_ssl,
        smtp_server=account.smtp_server,
        smtp_port=account.smtp_port,
        smtp_ssl=account.smtp_ssl
    )
    db.add(db_account)
    db.commit()
    db.refresh(db_account)
    return success(db_account, msg="邮箱账户添加成功")

@router.post("/validate")
async def validate_email_account(
    account: EmailAccountValidate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    验证邮箱账户配置。
    - 如果提供了密码，则使用新密码验证。
    - 如果未提供密码，则从数据库中查找现有账户的密码进行验证。
    """
    password_to_use = account.password
    
    # 如果请求中没有密码，尝试从数据库中获取
    if not password_to_use:
        existing_account = db.query(EmailAccount).filter(
            EmailAccount.email == account.email,
            EmailAccount.user_id == current_user.id
        ).first()
        if existing_account:
            password_to_use = existing_account.password
        else:
            # 在创建新账户的场景下，密码是必需的
            return fail("密码是必填项")

    # 验证 IMAP
    try:
        if account.imap_ssl:
            context = ssl.create_default_context()
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            imap_server = imaplib.IMAP4_SSL(account.imap_server, account.imap_port, ssl_context=context)
        else:
            imap_server = imaplib.IMAP4(account.imap_server, account.imap_port)
        
        imap_server.login(account.email, password_to_use)
        imap_server.logout()
    except Exception as e:
        return fail(f"IMAP 连接失败: {e}")

    # 验证 SMTP
    try:
        if account.smtp_ssl:
            context = ssl.create_default_context()
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            smtp_server = smtplib.SMTP_SSL(account.smtp_server, account.smtp_port, context=context)
        else:
            smtp_server = smtplib.SMTP(account.smtp_server, account.smtp_port)
        
        smtp_server.login(account.email, password_to_use)
        smtp_server.quit()
    except Exception as e:
        return fail(f"SMTP 连接失败: {e}")

    return success(msg="邮箱配置验证成功")

@router.put("/order")
async def update_account_order(
    payload: AccountOrderUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    更新邮箱账户的显示顺序
    """
    for index, account_id in enumerate(payload.account_ids):
        account = db.query(EmailAccount).filter(
            EmailAccount.id == account_id,
            EmailAccount.user_id == current_user.id
        ).first()
        if account:
            account.display_order = index
    
    db.commit()
    return success(msg="账户顺序已更新")

@router.get("/{account_id}")
async def get_email_account(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取指定邮箱账户信息
    """
    account = db.query(EmailAccount).filter(
        EmailAccount.id == account_id,
        EmailAccount.user_id == current_user.id
    ).first()
    if not account:
        return fail("邮箱账户未找到")
    return success(account)

@router.put("/{account_id}")
async def update_email_account(
    account_id: int,
    account_update: EmailAccountUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    更新邮箱账户信息
    """
    account = db.query(EmailAccount).filter(
        EmailAccount.id == account_id,
        EmailAccount.user_id == current_user.id
    ).first()
    if not account:
        return fail("邮箱账户未找到")
    
    update_data = account_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(account, field, value)
    
    db.commit()
    db.refresh(account)
    return success(account, msg="邮箱账户更新成功")

@router.delete("/{account_id}")
async def delete_email_account(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    删除邮箱账户
    """
    account = db.query(EmailAccount).filter(
        EmailAccount.id == account_id,
        EmailAccount.user_id == current_user.id
    ).first()
    if not account:
        return fail("邮箱账户未找到")
    
    db.delete(account)
    db.commit()
    return success(msg="邮箱账户删除成功")

@router.post("/{account_id}/sync")
async def sync_email_account(
    account_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    在后台同步邮箱账户
    """
    account = db.query(EmailAccount).filter(
        EmailAccount.id == account_id,
        EmailAccount.user_id == current_user.id
    ).first()
    if not account:
        return fail("邮箱账户未找到")

    if account.sync_status == "syncing":
        return fail("账户已在同步中，请稍后再试")

    # 更新账户状态为 'queuing' 或 'pending'
    account.sync_status = "syncing"
    db.add(account)
    db.commit()

    # 创建同步服务实例，只传递 account_id
    email_service = EmailService(account_id=account.id)
    # 将同步任务添加到后台
    background_tasks.add_task(email_service.sync_emails)
    
    return success(msg="已开始在后台同步邮件", data={"account_id": account_id})

@router.get("/{account_id}/folders")
async def get_email_folders(
    account_id: int,
    force_refresh: bool = Query(default=False, description="是否强制刷新缓存"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取邮箱账户的文件夹列表，包括自定义文件夹
    使用文件缓存优化性能，每个账号一个缓存
    """
    account = db.query(EmailAccount).filter(
        EmailAccount.id == account_id,
        EmailAccount.user_id == current_user.id
    ).first()
    if not account:
        return fail("邮箱账户未找到")

    # 缓存键：account_folders:{account_id}
    cache_key = f"account_folders:{account_id}"
    
    # 尝试从缓存读取
    if not force_refresh:
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            logger.debug(f"[缓存命中] 从缓存获取账户 {account_id} 的文件夹映射")
            # 从缓存获取文件夹映射
            folder_mapping = cached_data.get("folder_mapping", {})
            final_folders = cached_data.get("final_folders", [])
            
            # 返回缓存的数据
            return success(final_folders)
    
    # 缓存未命中或强制刷新，从IMAP服务器获取
    logger.debug(f"[缓存未命中] 从IMAP服务器获取账户 {account_id} 的文件夹列表")

    # 固定文件夹（包含系统草稿箱）
    fixed_folders_top = [
        {"name": "INBOX", "display_name": "收件箱"},
        {"name": "UNREAD", "display_name": "未读邮件"},
    ]
    
    fixed_folders_bottom = [
        {"name": "Drafts", "display_name": "草稿箱"},  # 系统自带的草稿箱
        {"name": "Sent", "display_name": "已发送"},
        {"name": "Junk", "display_name": "垃圾邮件"},
        {"name": "Trash", "display_name": "已删除"},
    ]
    
    # 用于过滤的固定文件夹名称集合（过滤掉服务器的草稿箱）
    fixed_folder_names = {"INBOX", "UNREAD", "SENT", "JUNK", "TRASH", "草稿", "DRAFTS", "DRAFT"}

    custom_folders = []
    folder_mapping = {}  # 存储文件夹名称到编码的映射
    
    try:
        if account.imap_ssl:
            imap = imaplib.IMAP4_SSL(account.imap_server, account.imap_port)
        else:
            imap = imaplib.IMAP4(account.imap_server, account.imap_port)
        
        imap.login(account.email, account.password)
        
        status, folders_data = imap.list()
        if status == 'OK':
            all_folders = []
            for folder_line in folders_data:
                line_str = folder_line.decode('utf-8', 'ignore')
                match = re.match(r'\((.*?)\)\s+"(.*?)"\s+"(.*)"', line_str)
                if match:
                    flags, delimiter, name = match.groups()
                    if "\\Noselect" not in flags:
                        decoded_name = decode_modified_utf7(name)
                        
                        # 添加特殊文件夹名称映射
                        if r'\Sent' in flags:
                            decoded_name = "Sent"
                            folder_mapping["Sent"] = {
                                "display_name": "已发送",
                                "encoded_name": name,
                                "flags": flags
                            }
                        elif r'\Junk' in flags:
                            decoded_name = "Junk"
                            folder_mapping["Junk"] = {
                                "display_name": "垃圾邮件",
                                "encoded_name": name,
                                "flags": flags
                            }
                        elif r'\Trash' in flags:
                            decoded_name = "Trash"
                            folder_mapping["Trash"] = {
                                "display_name": "已删除",
                                "encoded_name": name,
                                "flags": flags
                            }
                        
                        # 添加到映射表
                        if decoded_name not in folder_mapping:
                            folder_mapping[decoded_name] = {
                                "display_name": decoded_name,
                                "encoded_name": name,
                                "flags": flags
                            }
                        
                        all_folders.append({'name': name, 'decoded_name': decoded_name, 'delimiter': delimiter, 'flags': flags})

            # 过滤自定义文件夹（过滤掉所有固定文件夹，包括服务器的草稿箱）
            custom_folder_list = []
            
            for folder in sorted(all_folders, key=lambda x: x['decoded_name']):
                folder_name_upper = folder['decoded_name'].upper()
                
                # 跳过所有固定文件夹（包括服务器的草稿箱）
                if folder_name_upper in fixed_folder_names:
                    continue
                
                # 额外检查是否包含"草稿"关键字
                if "草稿" in folder['decoded_name'] or "DRAFT" in folder_name_upper:
                    continue
                    
                custom_folder_list.append(folder)
            
            # 构建自定义文件夹的层级结构
            root_folders = {}
            for folder in custom_folder_list:
                parts = folder['decoded_name'].split(folder['delimiter'])
                current_level = root_folders

                for i, part in enumerate(parts):
                    if part not in current_level:
                        current_level[part] = {
                            "name": folder['decoded_name'],
                            "display_name": part,
                            "children": {}
                        }
                    current_level = current_level[part]["children"]
            
            # 转换成列表格式
            def build_list(tree):
                result = []
                for key, value in tree.items():
                    item = {
                        "name": value["name"],
                        "display_name": value["display_name"]
                    }
                    if value["children"]:
                        item["children"] = build_list(value["children"])
                    result.append(item)
                return result

            custom_folders = build_list(root_folders)

        imap.logout()

    except Exception as e:
        logger.error(f"获取邮箱文件夹失败: {e}")
        # 即使获取失败，也返回固定文件夹列表
        final_folders = fixed_folders_top + fixed_folders_bottom
        return success(final_folders)
    
    # 组装最终的文件夹列表：
    # 顶部固定文件夹 + 自定义文件夹 + 底部固定文件夹（包含系统草稿箱）
    final_folders = fixed_folders_top.copy()
    final_folders.extend(custom_folders)
    final_folders.extend(fixed_folders_bottom)
    
    # 缓存文件夹映射和最终列表（24小时过期）
    cache_data = {
        "folder_mapping": folder_mapping,
        "final_folders": final_folders
    }
    cache.set(cache_key, cache_data, expire=86400)  # 24小时
    logger.debug(f"[缓存已更新] 账户 {account_id} 的文件夹映射已缓存")
    
    return success(final_folders)


@router.post("/{account_id}/folders", status_code=201)
async def create_folder(
    account_id: int,
    folder: FolderCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    为指定邮箱账户创建新文件夹
    """
    account = db.query(EmailAccount).filter(
        EmailAccount.id == account_id,
        EmailAccount.user_id == current_user.id
    ).first()
    if not account:
        return fail("邮箱账户未找到")

    try:
        email_service = EmailService(account_id=account.id)
        # This is a blocking IO call, should be run in an executor
        loop = asyncio.get_event_loop()
        success_flag = await loop.run_in_executor(
            None, email_service.create_folder, folder.folder_name, folder.parent_folder
        )
        if success_flag:
            # 清除文件夹缓存
            cache_key = f"account_folders:{account_id}"
            cache.delete(cache_key)
            logger.debug(f"[缓存已清除] 创建文件夹后清除账户 {account_id} 的文件夹缓存")
            return success(msg="文件夹创建成功")
        else:
            return fail(msg="文件夹已存在或创建失败")
    except Exception as e:
        return fail(msg=f"创建文件夹时出错: {e}")


@router.put("/{account_id}/folders")
async def rename_folder(
    account_id: int,
    folder_rename: FolderRename,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    重命名或移动指定邮箱账户的文件夹
    """
    account = db.query(EmailAccount).filter(
        EmailAccount.id == account_id,
        EmailAccount.user_id == current_user.id
    ).first()
    if not account:
        return fail("邮箱账户未找到")

    try:
        email_service = EmailService(account_id=account.id)
        loop = asyncio.get_event_loop()
        success_flag = await loop.run_in_executor(
            None, email_service.rename_folder, folder_rename.old_dir, folder_rename.new_dir
        )
        if success_flag:
            # 清除文件夹缓存
            cache_key = f"account_folders:{account_id}"
            cache.delete(cache_key)
            logger.debug(f"[缓存已清除] 重命名文件夹后清除账户 {account_id} 的文件夹缓存")
            return success(msg="文件夹重命名成功")
        else:
            return fail(msg="文件夹重命名失败")
    except Exception as e:
        return fail(msg=f"重命名文件夹时出错: {e}")


@router.get("/{account_id}/unread-count")
async def get_unread_email_count(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取指定邮箱账户的未读邮件数
    """
    from api.model.email import Email
    
    account = db.query(EmailAccount).filter(
        EmailAccount.id == account_id,
        EmailAccount.user_id == current_user.id
    ).first()
    if not account:
        return fail("邮箱账户未找到")

    unread_count = db.query(Email).filter(
        Email.email_account_id == account_id,
        Email.is_read == False,
        Email.folder != 'Trash',
        Email.is_deleted == False
    ).count()

    return success({"unread_count": unread_count})

@router.delete("/{account_id}/folders")
async def delete_folder(
    account_id: int,
    folder_data: FolderDelete,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    删除指定账户下的邮件文件夹，并触发后台同步
    """
    account = db.query(EmailAccount).filter(
        EmailAccount.id == account_id,
        EmailAccount.user_id == current_user.id
    ).first()
    if not account:
        return fail("邮箱账户未找到")

    email_service = EmailService(account=account)
    folder_name_to_delete = folder_data.folder_name
    try:
        email_service.delete_folder(folder_name_to_delete)
        
        # 清除文件夹缓存
        cache_key = f"account_folders:{account_id}"
        cache.delete(cache_key)
        logger.debug(f"[缓存已清除] 删除文件夹后清除账户 {account_id} 的文件夹缓存")
        
        # 文件夹删除成功后，触发一次后台同步
        # 创建一个新的EmailService实例，确保它使用最新的数据库会话
        sync_service = EmailService(account_id=account.id)
        background_tasks.add_task(sync_service.sync_emails)

        return success(msg=f"文件夹 '{folder_name_to_delete}' 已成功删除，并已开始后台同步。")
    except Exception as e:
        return fail(f"删除文件夹失败: {str(e)}")
