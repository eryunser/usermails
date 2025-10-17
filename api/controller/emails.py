import os
import re
import email
import base64
import shutil
import imaplib
import smtplib
from fastapi import APIRouter, Depends, Query, BackgroundTasks, Request, File, UploadFile
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from sqlalchemy import or_
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.header import Header
from email.utils import formatdate, make_msgid
from email import encoders

from api.database import get_db
from api.model.user import User
from api.model.email_account import EmailAccount
from api.model.email import Email
from api.controller.auth import get_current_user
from api.schemas.email.email import EmailResponse
from api.utils.response import success, fail
from api.service.email_service import EmailService
from api.utils.helpers import decode_url_encoded_str, encode_modified_utf7, decode_modified_utf7
from api.controller.ws import manager as ws_manager
from api.utils.logger import get_logger

# 初始化日志
logger = get_logger("emails")

class EmailIdList(BaseModel):
    email_ids: List[int]

class MarkAllAsReadPayload(BaseModel):
    folder: str

class SendEmailPayload(BaseModel):
    draft_id: Optional[int] = None  # 关联的草稿ID
    to: str
    cc: Optional[str] = None
    subject: str
    body: str
    attachments: Optional[List[str]] = None  # 附件文件路径列表（备用）

class MoveEmailPayload(BaseModel):
    current_folder: str
    target_folder: str

router = APIRouter()

@router.get("")
async def get_emails(
    account_id: int,
    folder: str = Query(default="INBOX", description="邮件文件夹"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    keyword: Optional[str] = Query(None, description="关键词，搜索标题和简介"),
    sender: Optional[str] = Query(None, description="发件人"),
    is_read: Optional[bool] = Query(None, description="是否已读"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取邮件列表
    在获取列表前，会先同步当前文件夹的最新邮件
    """
    account = db.query(EmailAccount).filter(
        EmailAccount.id == account_id,
        EmailAccount.user_id == current_user.id
    ).first()
    if not account:
        return fail("邮箱账户未找到")

    if folder:
        folder = decode_url_encoded_str(folder)

    # 在获取邮件列表之前，先同步当前文件夹
    # 虚拟文件夹需要特殊处理
    try:
        email_service = EmailService(account=account)
        
        # 判断是否为虚拟文件夹
        virtual_folders = ["UNREAD", "STARRED", "FLAGGED"]
        
        if folder.upper() in virtual_folders:
            # UNREAD是从多个文件夹筛选的，主要同步INBOX
            email_service._sync_folder_only({"original": "INBOX", "decoded": "INBOX", "flags": ""}, db)
        else:
            # 获取文件夹在服务器上的原始名称
            email_service._connect()
            
            # 查找文件夹的原始名称和flags
            folder_info = None
            try:
                status, folder_list = email_service.imap.list()
                if status == 'OK':
                    for folder_data in folder_list:
                        line_str = folder_data.decode('utf-8', 'ignore')
                        match = re.match(r'\((.*?)\)\s+"(.*?)"\s+"(.*)"', line_str)
                        if match:
                            flags, _, original_name = match.groups()
                            decoded_name = decode_modified_utf7(original_name)
                            
                            # 检查特殊文件夹
                            if folder == "Sent" and r'\Sent' in flags:
                                folder_info = {"original": original_name, "decoded": "Sent", "flags": flags}
                                break
                            elif folder == "Junk" and r'\Junk' in flags:
                                folder_info = {"original": original_name, "decoded": "Junk", "flags": flags}
                                break
                            elif folder == "Trash" and r'\Trash' in flags:
                                folder_info = {"original": original_name, "decoded": "Trash", "flags": flags}
                                break
                            elif decoded_name == folder:
                                folder_info = {"original": original_name, "decoded": decoded_name, "flags": flags}
                                break
            except Exception as e:
                logger.error(f"获取文件夹信息失败: {e}")
            
            email_service._disconnect()
            
            if folder_info:
                email_service._sync_folder_only(folder_info, db)
            else:
                # 如果找不到文件夹映射，使用默认值
                logger.error(f"未找到文件夹 '{folder}' 的映射信息，使用默认同步")
                encoded_folder = encode_modified_utf7(folder)
                email_service._sync_folder_only({"original": encoded_folder, "decoded": folder, "flags": ""}, db)
        
        logger.info(f"文件夹 '{folder}' 同步完成")
    except Exception as e:
        logger.error(f"同步文件夹 '{folder}' 时出错: {e}", exc_info=True)
        # 同步失败不影响后续查询，继续返回现有数据

    # 标准文件夹的处理逻辑
    if folder == "UNREAD":
        query = db.query(Email).filter(
            Email.email_account_id == account_id,
            Email.is_read == False,
            Email.folder.notin_(['Trash', 'Junk'])
        )
    else:
        query = db.query(Email).filter(
            Email.email_account_id == account_id,
            Email.folder == folder
        )

    if sender:
        query = query.filter(Email.sender.contains(sender))
    
    if keyword:
        query = query.filter(
            or_(
                Email.subject.contains(keyword),
                Email.summary.contains(keyword)
            )
        )

    if is_read is not None:
        query = query.filter(Email.is_read == is_read)
    
    total = query.count()
    emails = query.order_by(Email.received_date.desc()).offset(skip).limit(limit).all()
    
    return success(emails, count=total)

@router.get("/{email_id}")
async def get_email(
    account_id: int,
    email_id: int,
    background_tasks: BackgroundTasks,
    folder: str = Query(None, description="邮件所在的文件夹, 用于区分已发送邮件"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取单封邮件详情
    """
    account = db.query(EmailAccount).filter(
        EmailAccount.id == account_id,
        EmailAccount.user_id == current_user.id
    ).first()
    if not account:
        return fail("邮箱账户未找到")

    email_record = db.query(Email).filter(
        Email.id == email_id,
        Email.email_account_id == account_id
    ).first()

    if not email_record:
        return fail("邮件未找到")

    # 对于收件箱邮件，标记为已读
    if not email_record.is_read:
        email_record.is_read = True
        db.commit()
        db.refresh(email_record)
        background_tasks.add_task(ws_manager.broadcast_unread_count_update, current_user.id)

    email_data = EmailResponse.from_orm(email_record).dict()
    email_data['to'] = email_data.pop('recipients', None)

    return success(email_data)

@router.get("/{email_id}/content")
async def get_email_content(
    request: Request,
    account_id: int,
    email_id: int,
    folder: str = Query(None, description="邮件所在的文件夹, 用于区分已发送邮件"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取解析后的邮件正文（HTML或纯文本），并处理内嵌图片
    【重构版】：按需从IMAP获取正文，不下载附件
    """
    account = db.query(EmailAccount).filter(
        EmailAccount.id == account_id,
        EmailAccount.user_id == current_user.id
    ).first()
    if not account:
        return fail("邮箱账户未找到")

    email_record = db.query(Email).filter(
        Email.id == email_id,
        Email.email_account_id == account_id
    ).first()

    if not email_record:
        return fail("邮件记录未找到")

    # 使用新的按需获取方法
    email_service = EmailService(account=account)
    
    try:
        # 1. 获取邮件正文内容（不含附件）
        text_body, html_body, inline_images = email_service.fetch_email_content_on_demand(db, email_record)
        
        # 2. 获取附件列表信息（不下载附件内容）
        attachments = email_service.fetch_email_attachments_info(db, email_record)
        
        # 3. 处理返回内容
        content_to_return = html_body if html_body else text_body.replace("\n", "<br>")
        
        # 4. 替换HTML中的cid链接为base64 data URI
        if html_body and inline_images:
            for cid, image in inline_images.items():
                b64_data = base64.b64encode(image["data"]).decode('utf-8')
                data_uri = f"data:{image['type']};base64,{b64_data}"
                content_to_return = content_to_return.replace(f"cid:{cid}", data_uri)
        
        return success({
            "content": content_to_return,
            "attachments": attachments
        })
        
    except Exception as e:
        return fail(f"获取邮件内容失败: {str(e)}")

@router.get("/{email_id}/attachments/{attachment_index}")
async def download_attachment(
    account_id: int,
    email_id: int,
    attachment_index: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    下载邮件附件
    【重构版】：按需从IMAP获取单个附件
    """
    from fastapi.responses import Response
    
    account = db.query(EmailAccount).filter(
        EmailAccount.id == account_id,
        EmailAccount.user_id == current_user.id
    ).first()
    if not account:
        return fail("邮箱账户未找到")

    email_record = db.query(Email).filter(
        Email.id == email_id,
        Email.email_account_id == account_id
    ).first()

    if not email_record:
        return fail("邮件未找到")

    # 使用新的按需获取单个附件方法
    email_service = EmailService(account=account)
    
    try:
        filename, content_type, data = email_service.fetch_single_attachment(db, email_record, attachment_index)
        
        # 返回附件
        return Response(
            content=data,
            media_type=content_type,
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"'
            }
        )
        
    except Exception as e:
        return fail(f"下载附件失败: {str(e)}")

@router.post("/{email_id}/move")
async def move_email(
    account_id: int,
    email_id: int,
    payload: MoveEmailPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    移动邮件到指定文件夹
    """
    account = db.query(EmailAccount).filter(
        EmailAccount.id == account_id,
        EmailAccount.user_id == current_user.id
    ).first()
    if not account:
        return fail("邮箱账户未找到")

    email_service = EmailService(account=account)
    try:
        email_service.move_email(db, email_id, payload.current_folder, payload.target_folder)
        return success(msg="邮件移动成功")
    except Exception as e:
        return fail(f"邮件移动失败: {str(e)}")

@router.put("/{email_id}/read")
async def mark_email_read(
    account_id: int,
    email_id: int,
    background_tasks: BackgroundTasks,
    is_read: bool = True,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    标记邮件为已读/未读
    """
    account = db.query(EmailAccount).filter(
        EmailAccount.id == account_id,
        EmailAccount.user_id == current_user.id
    ).first()
    if not account:
        return fail("邮箱账户未找到")
    
    email_to_update = db.query(Email).filter(
        Email.id == email_id,
        Email.email_account_id == account_id
    ).first()
    
    if not email_to_update:
        return fail("邮件未找到")
    
    if email_to_update.is_read != is_read:
        try:
            # 1. 更新IMAP服务器上的状态
            if account.imap_ssl:
                imap = imaplib.IMAP4_SSL(account.imap_server, account.imap_port)
            else:
                imap = imaplib.IMAP4(account.imap_server, account.imap_port)
            imap.login(account.email, account.password)
            
            # 编码文件夹名称
            encoded_folder = encode_modified_utf7(email_to_update.folder)
            imap.select(f'"{encoded_folder}"')
            
            # 确保UID是字符串格式
            uid_str = str(email_to_update.uid)
            if is_read:
                imap.uid('store', uid_str, '+FLAGS', '(\\Seen)')
            else:
                imap.uid('store', uid_str, '-FLAGS', '(\\Seen)')
            imap.logout()

            # 2. 更新数据库
            email_to_update.is_read = is_read
            db.commit()
            background_tasks.add_task(ws_manager.broadcast_unread_count_update, current_user.id)
            
        except Exception as e:
            db.rollback()
            return fail(f"更新邮件状态失败: {e}")

    return success(msg="邮件状态更新成功")

@router.post("/mark-as-unread")
async def mark_emails_as_unread(
    account_id: int,
    payload: EmailIdList,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    批量标记邮件为未读
    """
    account = db.query(EmailAccount).filter(
        EmailAccount.id == account_id,
        EmailAccount.user_id == current_user.id
    ).first()
    if not account:
        return fail("邮箱账户未找到")

    emails_to_mark = db.query(Email).filter(
        Email.id.in_(payload.email_ids),
        Email.email_account_id == account_id
    ).all()

    if not emails_to_mark:
        return fail("未找到要标记的邮件")

    try:
        if account.imap_ssl:
            imap = imaplib.IMAP4_SSL(account.imap_server, account.imap_port)
        else:
            imap = imaplib.IMAP4(account.imap_server, account.imap_port)
        imap.login(account.email, account.password)
        
        # 按文件夹分组处理
        from collections import defaultdict
        emails_by_folder = defaultdict(list)
        for email_item in emails_to_mark:
            if email_item.is_read:
                emails_by_folder[email_item.folder].append(email_item)
        
        # 对每个文件夹分别处理
        updated = False
        for folder_name, emails in emails_by_folder.items():
            encoded_folder = encode_modified_utf7(folder_name)
            imap.select(f'"{encoded_folder}"')
            
            for email_item in emails:
                uid_str = str(email_item.uid)
                imap.uid('store', uid_str, '-FLAGS', '(\\Seen)')
                email_item.is_read = False
                updated = True
        
        imap.logout()
        
        if updated:
            db.commit()
            background_tasks.add_task(ws_manager.broadcast_unread_count_update, current_user.id)
            
        return success(msg="邮件已批量标记为未读")
    except Exception as e:
        db.rollback()
        return fail(f"批量标记邮件为未读失败: {e}")

@router.post("/mark-as-read")
async def mark_emails_as_read(
    account_id: int,
    payload: EmailIdList,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    批量标记邮件为已读
    """
    account = db.query(EmailAccount).filter(
        EmailAccount.id == account_id,
        EmailAccount.user_id == current_user.id
    ).first()
    if not account:
        return fail("邮箱账户未找到")

    emails_to_mark = db.query(Email).filter(
        Email.id.in_(payload.email_ids),
        Email.email_account_id == account_id
    ).all()

    if not emails_to_mark:
        return fail("未找到要标记的邮件")

    try:
        if account.imap_ssl:
            imap = imaplib.IMAP4_SSL(account.imap_server, account.imap_port)
        else:
            imap = imaplib.IMAP4(account.imap_server, account.imap_port)
        imap.login(account.email, account.password)
        
        # 按文件夹分组处理
        from collections import defaultdict
        emails_by_folder = defaultdict(list)
        for email_item in emails_to_mark:
            if not email_item.is_read:
                emails_by_folder[email_item.folder].append(email_item)
        
        # 对每个文件夹分别处理
        updated = False
        for folder_name, emails in emails_by_folder.items():
            encoded_folder = encode_modified_utf7(folder_name)
            imap.select(f'"{encoded_folder}"')
            
            for email_item in emails:
                uid_str = str(email_item.uid)
                imap.uid('store', uid_str, '+FLAGS', '(\\Seen)')
                email_item.is_read = True
                updated = True
        
        imap.logout()
        
        if updated:
            db.commit()
            background_tasks.add_task(ws_manager.broadcast_unread_count_update, current_user.id)
            
        return success(msg="邮件已批量标记为已读")
    except Exception as e:
        db.rollback()
        return fail(f"批量标记邮件为已读失败: {e}")

@router.post("/mark-all-as-read")
async def mark_all_as_read(
    account_id: int,
    payload: MarkAllAsReadPayload,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    将特定文件夹中的所有邮件标记为已读
    """
    account = db.query(EmailAccount).filter(
        EmailAccount.id == account_id,
        EmailAccount.user_id == current_user.id
    ).first()
    if not account:
        return fail("邮箱账户未找到")

    # 查询所有未读邮件
    query = db.query(Email).filter(
        Email.email_account_id == account_id,
        Email.is_read == False
    )

    # UNREAD 是一个虚拟文件夹，代表所有未读邮件，不按 folder 字段过滤
    if payload.folder != "UNREAD":
        query = query.filter(Email.folder == payload.folder)

    emails_to_mark = query.all()
    
    if not emails_to_mark:
        return success(msg="没有需要标记的邮件")

    try:
        # 1. 先更新IMAP服务器
        if account.imap_ssl:
            imap = imaplib.IMAP4_SSL(account.imap_server, account.imap_port)
        else:
            imap = imaplib.IMAP4(account.imap_server, account.imap_port)
        imap.login(account.email, account.password)
        
        # 按文件夹分组处理（因为需要选择不同的文件夹）
        from collections import defaultdict
        emails_by_folder = defaultdict(list)
        for email_item in emails_to_mark:
            emails_by_folder[email_item.folder].append(email_item)
        
        # 对每个文件夹批量标记
        for folder, emails in emails_by_folder.items():
            encoded_folder = encode_modified_utf7(folder)
            imap.select(f'"{encoded_folder}"')
            
            # 批量标记：将所有UID组合成逗号分隔的字符串
            uid_list = ','.join([str(email.uid) for email in emails])
            imap.uid('store', uid_list, '+FLAGS', '(\\Seen)')
        
        imap.logout()

        # 2. 再批量更新数据库
        email_ids = [email.id for email in emails_to_mark]
        db.query(Email).filter(Email.id.in_(email_ids)).update(
            {Email.is_read: True}, 
            synchronize_session=False
        )
        db.commit()
        
        background_tasks.add_task(ws_manager.broadcast_unread_count_update, current_user.id)
        return success(msg=f"操作完成，{len(emails_to_mark)} 封邮件已标记为已读。")
        
    except Exception as e:
        db.rollback()
        return fail(f"批量标记已读失败: {e}")

@router.delete("")
async def delete_emails(
    account_id: int,
    payload: EmailIdList,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    批量删除邮件(移动到已删除文件夹)
    """
    account = db.query(EmailAccount).filter(
        EmailAccount.id == account_id,
        EmailAccount.user_id == current_user.id
    ).first()
    if not account:
        return fail("邮箱账户未找到")

    email_service = EmailService(account=account)
    try:
        # 注意：在调用 move_emails_to_trash 之前，需要先关闭现有的数据库会话
        # 因为该方法会自己创建新的会话。或者改造 EmailService 以接收现有会-话。
        # 为简单起见，这里我们直接调用，依赖其内部的会话管理。
        # 如果遇到会话问题，需要回来调整。
        email_service.move_emails_to_trash(db, payload.email_ids)
        
        background_tasks.add_task(ws_manager.broadcast_unread_count_update, current_user.id)
        return success(msg="邮件已成功移动到回收站")
    except Exception as e:
        return fail(f"移动邮件到回收站失败: {str(e)}")

@router.delete("/{email_id}")
async def permanent_delete_email(
    account_id: int,
    email_id: int,
    background_tasks: BackgroundTasks,
    folder: str = Query(None, description="邮件所在的文件夹"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    彻底删除单封邮件
    """
    account = db.query(EmailAccount).filter(
        EmailAccount.id == account_id,
        EmailAccount.user_id == current_user.id
    ).first()
    if not account:
        return fail("邮箱账户未找到")

    email_to_delete = db.query(Email).filter(
        Email.id == email_id,
        Email.email_account_id == account_id
    ).first()

    if not email_to_delete:
        return fail("未找到要删除的邮件")

    try:
        # 1. 从IMAP服务器删除
        if account.imap_ssl:
            imap = imaplib.IMAP4_SSL(account.imap_server, account.imap_port)
        else:
            imap = imaplib.IMAP4(account.imap_server, account.imap_port)
        imap.login(account.email, account.password)
        
        # 获取文件夹映射
        folder_name = email_to_delete.folder
        folder_mapping = {}
        try:
            status, folder_list = imap.list()
            if status == 'OK':
                for folder_data in folder_list:
                    line_str = folder_data.decode('utf-8', 'ignore')
                    match = re.match(r'\((.*?)\)\s+"(.*?)"\s+"(.*)"', line_str)
                    if match:
                        flags, _, original_name = match.groups()
                        decoded_name = decode_modified_utf7(original_name)
                        
                        if r'\Sent' in flags:
                            folder_mapping["Sent"] = original_name
                        elif r'\Junk' in flags:
                            folder_mapping["Junk"] = original_name
                        elif r'\Trash' in flags:
                            folder_mapping["Trash"] = original_name
                        
                        folder_mapping[decoded_name] = original_name
        except Exception as e:
            logger.error(f"获取文件夹列表失败: {e}")
        
        # 使用真实文件夹名称
        original_folder_name = folder_mapping.get(folder_name, encode_modified_utf7(folder_name))
        status, data = imap.select(f'"{original_folder_name}"')
        
        if status == 'OK':
            # 确保UID是字符串格式
            uid_str = str(email_to_delete.uid)
            imap.uid('store', uid_str, '+FLAGS', '(\\Deleted)')
            imap.expunge()
        
        imap.logout()

        # 2. 删除本地 .eml 文件
        if email_to_delete.eml_path and os.path.exists(email_to_delete.eml_path):
            os.remove(email_to_delete.eml_path)

        # 3. 从数据库删除
        db.delete(email_to_delete)
        db.commit()
        background_tasks.add_task(ws_manager.broadcast_unread_count_update, current_user.id)

        return success(msg="邮件已彻底删除")
    except Exception as e:
        db.rollback()
        return fail(f"彻底删除邮件时出错: {e}")

@router.post("/permanent-delete")
async def permanent_delete_selected_emails(
    account_id: int,
    payload: EmailIdList,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    批量彻底删除邮件
    """
    import logging
    logger = logging.getLogger(__name__)
    
    account = db.query(EmailAccount).filter(
        EmailAccount.id == account_id,
        EmailAccount.user_id == current_user.id
    ).first()
    if not account:
        return fail("邮箱账户未找到")

    emails_to_delete = db.query(Email).filter(
        Email.id.in_(payload.email_ids),
        Email.email_account_id == account_id
    ).all()

    if not emails_to_delete:
        return fail("未找到要删除的邮件")

    try:
        logger.info(f"开始批量删除 {len(emails_to_delete)} 封邮件")
        
        if account.imap_ssl:
            imap = imaplib.IMAP4_SSL(account.imap_server, account.imap_port)
        else:
            imap = imaplib.IMAP4(account.imap_server, account.imap_port)
        imap.login(account.email, account.password)
        logger.info("IMAP 登录成功")

        # 按文件夹分组处理邮件
        from collections import defaultdict
        emails_by_folder = defaultdict(list)
        for email_item in emails_to_delete:
            emails_by_folder[email_item.folder].append(email_item)
        
        logger.info(f"邮件分布在 {len(emails_by_folder)} 个文件夹中: {list(emails_by_folder.keys())}")

        # 获取IMAP文件夹列表，建立映射关系
        folder_mapping = {}
        try:
            status, folder_list = imap.list()
            if status == 'OK':
                for folder_data in folder_list:
                    line_str = folder_data.decode('utf-8', 'ignore')
                    match = re.match(r'\((.*?)\)\s+"(.*?)"\s+"(.*)"', line_str)
                    if match:
                        flags, _, original_name = match.groups()
                        decoded_name = decode_modified_utf7(original_name)
                        
                        # 处理特殊文件夹标记
                        if r'\Sent' in flags:
                            folder_mapping["Sent"] = original_name
                        elif r'\Junk' in flags:
                            folder_mapping["Junk"] = original_name
                        elif r'\Trash' in flags:
                            folder_mapping["Trash"] = original_name
                        
                        folder_mapping[decoded_name] = original_name
            logger.info(f"文件夹映射: {folder_mapping}")
        except Exception as e:
            logger.error(f"获取文件夹列表失败: {e}")
        
        # 对每个文件夹分别处理
        for folder_name, emails in emails_by_folder.items():
            logger.info(f"处理文件夹: {folder_name}, 包含 {len(emails)} 封邮件")
            
            # 获取服务器上的真实文件夹名称
            original_folder_name = folder_mapping.get(folder_name, encode_modified_utf7(folder_name))
            logger.info(f"使用服务器文件夹名称: {original_folder_name}")
            
            # 选择文件夹并检查返回状态
            status, data = imap.select(f'"{original_folder_name}"')
            logger.info(f"SELECT 文件夹 {original_folder_name} 状态: {status}, 数据: {data}")
            
            if status != 'OK':
                # 如果无法选择文件夹，说明该文件夹在IMAP服务器上不存在
                # 直接从本地数据库和文件系统删除这些邮件
                logger.error(f"无法选择文件夹 {folder_name}，将只从本地删除这些邮件")
                for email_item in emails:
                    # 删除本地 .eml 文件
                    if email_item.eml_path and os.path.exists(email_item.eml_path):
                        os.remove(email_item.eml_path)
                    # 从数据库删除
                    db.delete(email_item)
                continue
            
            # 批量标记该文件夹中的邮件为删除
            for email_item in emails:
                uid_str = str(email_item.uid)
                logger.info(f"标记邮件 UID {uid_str} 为删除")
                
                status, data = imap.uid('store', uid_str, '+FLAGS', '(\\Deleted)')
                logger.info(f"STORE 命令状态: {status}, 数据: {data}")
                
                if status != 'OK':
                    logger.error(f"无法在服务器上标记邮件 {uid_str} 为删除，将只从本地删除")
                
                # 删除本地 .eml 文件
                if email_item.eml_path and os.path.exists(email_item.eml_path):
                    os.remove(email_item.eml_path)
                
                # 从数据库删除
                db.delete(email_item)
            
            # 在当前文件夹中执行 expunge
            logger.info(f"执行 EXPUNGE 清理文件夹 {folder_name}")
            imap.expunge()

        imap.logout()
        logger.info("IMAP 退出登录")
        
        db.commit()
        background_tasks.add_task(ws_manager.broadcast_unread_count_update, current_user.id)
        return success(msg="选中的项目已彻底删除")
        
    except Exception as e:
        logger.error(f"批量彻底删除邮件出错: {str(e)}", exc_info=True)
        db.rollback()
        return fail(f"批量彻底删除邮件时出错: {e}")

@router.post("/images")
async def upload_image(
    account_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    上传图片
    """
    account = db.query(EmailAccount).filter(
        EmailAccount.id == account_id,
        EmailAccount.user_id == current_user.id
    ).first()
    if not account:
        return fail("邮箱账户未找到")

    upload_dir = "web/uploads/images"
    os.makedirs(upload_dir, exist_ok=True)
    
    # 生成唯一文件名
    file_extension = os.path.splitext(file.filename)[1]
    unique_filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{os.urandom(8).hex()}{file_extension}"
    file_path = os.path.join(upload_dir, unique_filename)
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # 返回相对于 web 根目录的相对路径
    return success(data={"url": f"uploads/images/{unique_filename}"})

@router.post("/send")
async def send_email(
    account_id: int,
    to: str = None,
    cc: str = None,
    subject: str = None,
    body: str = None,
    draft_id: int = None,
    attachments: List[UploadFile] = File(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    发送邮件，保存到已发送文件夹，并在成功后删除草稿
    支持附件上传
    """
    from api.model.draft import Draft
    
    account = db.query(EmailAccount).filter(
        EmailAccount.id == account_id,
        EmailAccount.user_id == current_user.id
    ).first()
    if not account:
        return fail("邮箱账户未找到")

    # 验证必填字段
    if not to or not subject or not body:
        return fail("收件人、主题和正文不能为空")

    # 创建邮件
    if attachments and len(attachments) > 0:
        # 有附件，使用MIMEMultipart
        msg = MIMEMultipart()
        msg['From'] = Header(f"{current_user.username} <{account.email}>", 'utf-8')
        msg['To'] = Header(to, 'utf-8')
        msg['Subject'] = Header(subject, 'utf-8')
        msg['Date'] = formatdate(localtime=True)
        msg['Message-ID'] = make_msgid()
        
        recipients_list = [to]
        if cc:
            msg['Cc'] = Header(cc, 'utf-8')
            recipients_list.extend(cc.split(','))
        
        # 添加邮件正文
        msg.attach(MIMEText(body, 'html', 'utf-8'))
        
        # 添加附件
        for attachment in attachments:
            # 读取附件内容
            content = await attachment.read()
            
            # 创建附件部分
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(content)
            encoders.encode_base64(part)
            
            # 添加文件名
            part.add_header(
                'Content-Disposition',
                f'attachment; filename="{attachment.filename}"'
            )
            
            msg.attach(part)
    else:
        # 无附件，使用简单的MIMEText
        msg = MIMEText(body, 'html', 'utf-8')
        msg['From'] = Header(f"{current_user.username} <{account.email}>", 'utf-8')
        msg['To'] = Header(to, 'utf-8')
        msg['Subject'] = Header(subject, 'utf-8')
        msg['Date'] = formatdate(localtime=True)
        msg['Message-ID'] = make_msgid()
        
        recipients_list = [to]
        if cc:
            msg['Cc'] = Header(cc, 'utf-8')
            recipients_list.extend(cc.split(','))

    try:
        # 1. 发送邮件
        if account.smtp_ssl:
            smtp_server = smtplib.SMTP_SSL(account.smtp_server, account.smtp_port)
        else:
            smtp_server = smtplib.SMTP(account.smtp_server, account.smtp_port)
        
        smtp_server.login(account.email, account.password)
        smtp_server.sendmail(account.email, recipients_list, msg.as_string())
        smtp_server.quit()

        # 2. 保存到 emails 表
        has_attachments = attachments and len(attachments) > 0
        sent_email = Email(
            email_account_id=account_id,
            uid="",
            message_id=msg['Message-ID'],
            subject=subject,
            sender=account.email,
            recipients=to,
            cc=cc,
            folder="Sent",
            is_read=True,
            sent_date=datetime.now(),
            received_date=datetime.now(),
            has_attachments=has_attachments
        )
        db.add(sent_email)
        db.commit()
        db.refresh(sent_email)
        
        # 3. 保存为 .eml 文件
        email_dir = os.path.join("emails", account.email.replace('@', '_at_'))
        os.makedirs(email_dir, exist_ok=True)
        eml_path = os.path.join(email_dir, f"{sent_email.id}.eml")
        
        with open(eml_path, 'wb') as f:
            f.write(msg.as_bytes())
        
        sent_email.eml_path = eml_path
        db.commit()

        # 4. 如果有关联的草稿，发送成功后删除它
        if draft_id:
            draft_to_delete = db.query(Draft).filter(Draft.id == draft_id).first()
            if draft_to_delete:
                db.delete(draft_to_delete)
                db.commit()

        return success(msg="邮件发送成功")
    except Exception as e:
        logger.error(f"邮件发送失败: {e}", exc_info=True)
        db.rollback()
        return fail(f"邮件发送失败: {e}")
