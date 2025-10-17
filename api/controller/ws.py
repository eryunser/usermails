import asyncio
import imaplib
import json
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.orm import Session
from api.database import SessionLocal
from api.model.user import User
from api.model.email_account import EmailAccount
from api.model.email import Email
from api.model.draft import Draft
from api.controller.auth import get_current_user_from_token
from api.service.email_service import EmailService
from api.utils.logger import get_logger

# 初始化日志
logger = get_logger("ws")

router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[int, WebSocket] = {}

    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        self.active_connections[user_id] = websocket

    def disconnect(self, user_id: int):
        if user_id in self.active_connections:
            del self.active_connections[user_id]

    async def send_personal_message(self, message: str, user_id: int):
        if user_id in self.active_connections:
            await self.active_connections[user_id].send_text(message)

    async def broadcast_unread_count_update(self, user_id: int):
        """Triggers an immediate unread count update for a user."""
        if user_id in self.active_connections:
            db = SessionLocal()
            try:
                counts = get_unread_counts(db, user_id)
                await self.send_personal_message(
                    json.dumps({"status": "unread_count_update", "counts": counts}),
                    user_id
                )
            finally:
                db.close()

manager = ConnectionManager()

def get_unread_counts(db: Session, user_id: int) -> dict[int, int]:
    """获取用户所有邮箱账户的未读邮件数"""
    accounts = db.query(EmailAccount).filter(EmailAccount.user_id == user_id).all()
    unread_counts = {}
    for account in accounts:
        count = db.query(Email).filter(Email.email_account_id == account.id, Email.is_read == False).count()
        unread_counts[account.id] = count
    return unread_counts

async def check_new_mail_realtime(account: EmailAccount):
    """
    连接到IMAP服务器，检查收件箱中的邮件数量
    """
    try:
        if account.imap_ssl:
            imap = imaplib.IMAP4_SSL(account.imap_server, account.imap_port)
        else:
            imap = imaplib.IMAP4(account.imap_server, account.imap_port)
        
        imap.login(account.email, account.password)
        status, messages = imap.select("INBOX")
        imap.logout()
        
        if status == "OK":
            return int(messages[0])
    except Exception as e:
        logger.error(f"检查邮箱 {account.email} 出错: {e}")
    return None

def run_sync_in_background(account_id: int) -> bool:
    """Helper function to run sync in a thread and return its status."""
    email_service = EmailService(account_id=account_id)
    return email_service.sync_emails()

async def email_checker(user_id: int):
    """
    定期检查用户的邮件是否有更新，并发送心跳
    """
    server_email_counts = {}
    loop = asyncio.get_event_loop()
    last_mail_check_time = 0
    last_heartbeat_time = 0

    # 初始化检查
    try:
        with SessionLocal() as db:
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                for account in user.email_accounts:
                    count = await check_new_mail_realtime(account)
                    if count is not None:
                        server_email_counts[account.id] = count
    except Exception as e:
        logger.error(f"初始化邮件检查时出错: {e}")

    while True:
        now = loop.time()
        try:
            # 每10秒检查一次邮件
            if now - last_mail_check_time >= 10:
                last_mail_check_time = now
                update_found = False
                with SessionLocal() as db:
                    user = db.query(User).filter(User.id == user_id).first()
                    if not user:
                        logger.error(f"用户 {user_id} 未找到，停止检查。")
                        break

                    for account in user.email_accounts:
                        new_count = await check_new_mail_realtime(account)
                        if new_count is not None and new_count > server_email_counts.get(account.id, 0):
                            logger.info(f"检测到用户 {user.id} 的邮箱账户 {account.id} 有新邮件，触发后台同步")
                            update_found = True
                            
                            # 在线程中运行同步任务并获取结果
                            sync_successful = await loop.run_in_executor(None, run_sync_in_background, account.id)
                            
                            if sync_successful:
                                logger.info(f"邮箱账户 {account.id} 同步成功")
                                await manager.send_personal_message(f'{{"status": "new_mail", "accountId": {account.id}}}', user_id)
                                server_email_counts[account.id] = new_count
                            else:
                                logger.error(f"邮箱账户 {account.id} 同步失败，将在下一周期重试")
                                await manager.send_personal_message(f'{{"status": "sync_failed", "accountId": {account.id}}}', user_id)
                
                # This part is now handled by unread_count_updater
                # if not update_found:
                #     await manager.send_personal_message('{"status": "no_update"}', user_id)

            await asyncio.sleep(1) # 防止CPU占用过高

        except Exception as e:
            logger.error(f"邮件检查循环出错: {e}")
            await asyncio.sleep(10) # 发生错误时，等待一段时间再重试

async def unread_count_updater(user_id: int):
    """
    每5秒向客户端发送所有账户的未读邮件数
    """
    while True:
        await asyncio.sleep(5)
        db = SessionLocal()
        try:
            counts = get_unread_counts(db, user_id)
            await manager.send_personal_message(
                json.dumps({"status": "unread_count_update", "counts": counts}),
                user_id
            )
        except Exception as e:
            logger.error(f"更新未读邮件数时出错: {e}")
        finally:
            db.close()


@router.websocket("/ws/sync")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(...),
):
    """
    WebSocket端点，用于实时邮件同步通知
    """
    # 在这里使用一次性的db session来验证token
    db = SessionLocal()
    try:
        user = get_current_user_from_token(token, db)
        if not user:
            await websocket.close(code=1008)
            return
        user_id = user.id
    finally:
        db.close()

    await manager.connect(websocket, user_id)
    
    # 启动邮件检查任务
    checker_task = asyncio.create_task(email_checker(user_id))
    # 启动未读邮件数更新任务
    unread_updater_task = asyncio.create_task(unread_count_updater(user_id))

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # The 'get_drafts' action is no longer needed.
            pass

    except WebSocketDisconnect:
        manager.disconnect(user_id)
        checker_task.cancel()
        unread_updater_task.cancel()
        logger.info(f"用户 {user_id} 的WebSocket连接已断开")
