import os
import imaplib
import smtplib
import email
import ssl
import re
import html
import uuid
import socket
import base64
import hashlib
from email.header import decode_header
from datetime import datetime
from sqlalchemy import func
from sqlalchemy.orm import Session
from bs4 import BeautifulSoup
from fastapi import HTTPException
from fastapi import status as http_status
from api.database import SessionLocal
from api.model.email_account import EmailAccount
from api.model.email import Email
from api.utils.helpers import (
    decode_modified_utf7, 
    encode_modified_utf7,
    generate_content_hash,
    generate_imap_key,
    ensure_message_id
)
from api.utils.cache import cache
from api.utils.logger import get_logger
from api.service.email_service_optimized import EmailSyncOptimizer
import gc

# 初始化日志
logger = get_logger("email_service")

class EmailService:
    def __init__(self, account_id: int = None, account: EmailAccount = None):
        if account_id:
            self.account_id = account_id
            self.account = None
        elif account:
            self.account = account
            self.account_id = account.id
        self.imap = None
    
    def sync_emails(self):
        db: Session = SessionLocal()
        db.autoflush = False
        try:
            account = db.query(EmailAccount).filter(EmailAccount.id == self.account_id).first()
            if not account:
                logger.error(f"同步错误：未找到账户 ID {self.account_id}")
                return False

            self.account = account
            self.account.sync_status = "syncing"
            
            self._connect()
            
            folders = self._get_folders_to_sync()
            for folder in folders:
                self._sync_folder(folder, db)

            self.account.last_sync = datetime.utcnow()
            self.account.sync_status = "idle"
            
            db.commit()
            logger.info(f"账户 {self.account.email} 同步成功")
            return True
        except Exception as e:
            logger.error(f"邮件同步失败: {e}", exc_info=True)
            db.rollback()
            try:
                account_to_update = db.query(EmailAccount).filter(EmailAccount.id == self.account_id).first()
                if account_to_update:
                    account_to_update.sync_status = "failed"
                    db.commit()
            except Exception as inner_e:
                logger.error(f"设置同步状态为'失败'时出错: {inner_e}")
                db.rollback()
            return False
        finally:
            self._disconnect()

    def delete_folder(self, folder_name: str):
        """
        在IMAP服务器上删除指定的文件夹。
        如果文件夹不为空，则先将其中的所有邮件移动到收件箱。
        """
        db: Session = SessionLocal()
        try:
            self._connect()
            encoded_folder_name = encode_modified_utf7(folder_name)
            
            # 选择要删除的文件夹
            status, _ = self.imap.select(f'"{encoded_folder_name}"', readonly=False)
            
            # 如果文件夹存在或可选，则处理其中的邮件
            if status == 'OK':
                # 检查文件夹中是否有邮件
                status, uids_data = self.imap.uid('search', None, "ALL")
                if status == 'OK' and uids_data[0]:
                    uids = uids_data[0].split()
                    if uids:
                        # 将UID列表转换为逗号分隔的字符串
                        uid_set_str = b','.join(uids)
                        decoded_uids = [uid.decode() for uid in uids]
                        target_folder = "INBOX"
                        encoded_target_folder = encode_modified_utf7(target_folder)

                        # 1. 复制所有邮件到收件箱
                        copy_status, _ = self.imap.uid('COPY', uid_set_str, f'"{encoded_target_folder}"')
                        if copy_status != 'OK':
                            raise Exception(f"无法复制邮件到 '{target_folder}'")
                        
                        logger.info(f"已将 {len(uids)} 封邮件从 '{folder_name}' 复制到服务器上的 '{target_folder}'")

                        # 2. 在原文件夹中标记所有邮件为删除
                        store_status, _ = self.imap.uid('STORE', uid_set_str, '+FLAGS', '(\\Deleted)')
                        if store_status != 'OK':
                            logger.error(f"警告: 无法在 '{folder_name}' 中标记邮件为已删除")

                        # 3. 执行 expunge
                        self.imap.expunge()

                        # 4. 更新数据库
                        db.query(Email).filter(
                            Email.email_account_id == self.account.id,
                            Email.folder == folder_name,
                            Email.uid.in_(decoded_uids)
                        ).update({"folder": target_folder}, synchronize_session=False)
                        db.commit()
                        logger.info(f"已更新数据库中 {len(uids)} 条邮件记录到文件夹 '{target_folder}'")

                # 在删除前必须先关闭文件夹
                self.imap.close()
            
            # 执行删除操作
            status, response = self.imap.delete(f'"{encoded_folder_name}"')
            
            if status != 'OK':
                raise Exception(f"无法在服务器上删除文件夹: {response}")

            logger.info(f"文件夹 '{folder_name}' 已成功从IMAP服务器删除。")

        except Exception as e:
            db.rollback()
            logger.error(f"删除文件夹时发生异常: {e}", exc_info=True)
            # 重新抛出异常，以便控制器可以捕获它并返回适当的错误响应
            raise
        finally:
            self._disconnect()
            db.close()

    def move_emails_to_trash(self, db: Session, email_ids: list[int]):
        try:
            emails_to_move = db.query(Email).filter(Email.id.in_(email_ids)).all()
            if not emails_to_move:
                raise HTTPException(status_code=404, detail="未找到要移动到回收站的邮件")

            self._connect()
            
            target_folder = "Trash"
            encoded_target_folder = encode_modified_utf7(target_folder)

            # 假设所有邮件都在同一个文件夹，如果不是，需要按文件夹分组处理
            # 这里为了简化，我们假设它们都在同一个文件夹
            current_folder = emails_to_move[0].folder
            encoded_current_folder = encode_modified_utf7(current_folder)
            
            status, _ = self.imap.select(f'"{encoded_current_folder}"', readonly=False)
            if status != 'OK':
                raise HTTPException(status_code=500, detail=f"无法在服务器上选择文件夹 '{current_folder}'")

            for email_record in emails_to_move:
                # 1. 复制
                copy_result, _ = self.imap.uid('COPY', email_record.uid, f'"{encoded_target_folder}"')
                if copy_result != 'OK':
                    logger.error(f"警告: 无法将邮件 {email_record.id} 复制到回收站")
                    continue

                # 2. 标记删除
                store_result, _ = self.imap.uid('STORE', email_record.uid, '+FLAGS', '(\\Deleted)')
                if store_result != 'OK':
                     logger.error(f"警告: 无法在 '{current_folder}' 中标记邮件 {email_record.id} 为已删除")
                
                # 3. 更新数据库
                email_record.folder = target_folder
            
            # 4. 清理
            self.imap.expunge()

            db.commit()
            logger.info(f"已将 {len(emails_to_move)} 封邮件移至回收站")

        except Exception as e:
            db.rollback()
            logger.error(f"移动邮件到回收站失败: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            self._disconnect()
            db.close()

    def _get_original_folder_name(self, decoded_folder_name: str) -> str:
        """
        获取文件夹在服务器上的原始名称（优先从缓存获取）
        """
        # 尝试从缓存获取文件夹映射
        cache_key = f"account_folders:{self.account.id}"
        cached_data = cache.get(cache_key)
        
        if cached_data is not None:
            folder_mapping = cached_data.get("folder_mapping", {})
            if decoded_folder_name in folder_mapping:
                encoded_name = folder_mapping[decoded_folder_name].get("encoded_name")
                if encoded_name:
                    logger.debug(f"[缓存] 获取文件夹 '{decoded_folder_name}' 的编码名称: {encoded_name}")
                    return encoded_name
        
        # 缓存未命中，从IMAP服务器获取
        logger.debug(f"[缓存未命中] 从IMAP服务器获取文件夹 '{decoded_folder_name}' 的编码名称")
        try:
            status, folder_list = self.imap.list()
            if status == 'OK':
                for folder_data in folder_list:
                    line_str = folder_data.decode('utf-8', 'ignore')
                    match = re.match(r'\((.*?)\)\s+"(.*?)"\s+"(.*)"', line_str)
                    if match:
                        flags, _, original_name = match.groups()
                        decoded_name = decode_modified_utf7(original_name)
                        
                        # 检查是否是特殊文件夹
                        if decoded_folder_name == "Sent" and r'\Sent' in flags:
                            logger.debug(f"找到已发送文件夹: {original_name}")
                            return original_name
                        elif decoded_folder_name == "Junk" and r'\Junk' in flags:
                            logger.debug(f"找到垃圾邮件文件夹: {original_name}")
                            return original_name
                        elif decoded_folder_name == "Trash" and r'\Trash' in flags:
                            logger.debug(f"找到回收站文件夹: {original_name}")
                            return original_name
                        elif decoded_name == decoded_folder_name:
                            return original_name
        except Exception as e:
            logger.error(f"获取原始文件夹名称时出错: {e}")
        
        # 如果找不到，使用encode_modified_utf7编码后返回
        encoded_name = encode_modified_utf7(decoded_folder_name)
        logger.debug(f"文件夹 '{decoded_folder_name}' 未找到映射，使用编码名称: {encoded_name}")
        return encoded_name

    def fetch_and_cache_email_without_attachments(self, db: Session, email_record: Email):
        """
        获取邮件并缓存为.eml文件（排除附件内容）
        只保存邮件头、正文和内嵌图片，不保存附件
        返回：缓存的.eml文件路径
        """
        # 检查缓存是否已存在
        if email_record.eml_path and os.path.exists(email_record.eml_path):
            logger.debug(f"邮件 {email_record.id} 的缓存已存在: {email_record.eml_path}")
            return email_record.eml_path
        
        logger.info(f"缓存邮件 {email_record.id}（不含附件）")
        
        try:
            self._connect()
            
            original_folder_name = self._get_original_folder_name(email_record.folder)
            select_status, select_data = self.imap.select(f'"{original_folder_name}"', readonly=True)
            if select_status != 'OK':
                raise ConnectionError(f"无法选择文件夹")
            
            uid_str = str(email_record.uid)
            
            # 获取完整邮件
            fetch_status, msg_data = self.imap.uid('fetch', uid_str, '(BODY.PEEK[])')
            if fetch_status != 'OK' or not msg_data or msg_data[0] is None:
                raise ConnectionError(f"无法获取邮件内容")
            
            if not isinstance(msg_data[0], tuple) or len(msg_data[0]) < 2:
                raise ConnectionError(f"邮件数据结构异常")
            
            raw_email = msg_data[0][1]
            if not raw_email:
                raise ConnectionError(f"邮件数据为空")
            
            # 解析邮件
            original_msg = email.message_from_bytes(raw_email)
            
            # 创建新的邮件对象，复制头部
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            from email.mime.image import MIMEImage
            
            cached_msg = MIMEMultipart('mixed')
            
            # 复制所有邮件头
            for header, value in original_msg.items():
                cached_msg[header] = value
            
            # 遍历原始邮件，只保留正文和内嵌图片
            if original_msg.is_multipart():
                for part in original_msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition"))
                    content_id = part.get("Content-ID")
                    
                    # 跳过multipart容器本身
                    if part.get_content_maintype() == 'multipart':
                        continue
                    
                    # 跳过附件（非内嵌图片的附件）
                    if "attachment" in content_disposition and not content_id:
                        continue
                    
                    # 保留正文和内嵌图片
                    if content_type in ["text/plain", "text/html"] or content_id:
                        cached_msg.attach(part)
            else:
                # 单部分邮件，直接设置内容
                cached_msg.set_payload(original_msg.get_payload())
                cached_msg.set_charset(original_msg.get_content_charset())
            
            # 保存到文件
            filename = f"{email_record.id}.eml"
            dir_path = os.path.join("emails", self.account.email)
            os.makedirs(dir_path, exist_ok=True)
            file_path = os.path.join(dir_path, filename)
            
            with open(file_path, "wb") as f:
                f.write(cached_msg.as_bytes())
            
            # 更新数据库
            if email_record.eml_path != file_path:
                email_record.eml_path = file_path
                db.commit()
            
            logger.info(f"邮件 {email_record.id} 已缓存到 {file_path}（不含附件）")
            return file_path
            
        except Exception as e:
            logger.error(f"缓存邮件失败: {e}", exc_info=True)
            raise HTTPException(
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"缓存邮件失败: {e}"
            )
        finally:
            self._disconnect()
    
    def fetch_email_content_on_demand(self, db: Session, email_record: Email):
        """
        按需获取邮件内容（只获取正文，不包括附件）
        优先从缓存读取，如果没有缓存则从IMAP获取
        返回：(text_body, html_body, inline_images_dict)
        """
        logger.debug(f"获取邮件 {email_record.id} 的内容")
        
        # 1. 尝试从缓存读取
        if email_record.eml_path and os.path.exists(email_record.eml_path):
            logger.debug(f"从缓存读取邮件内容: {email_record.eml_path}")
            try:
                with open(email_record.eml_path, 'rb') as f:
                    raw_email = f.read()
                msg = email.message_from_bytes(raw_email)
                return self._parse_email_content(msg)
            except Exception as e:
                logger.error(f"从缓存读取失败，将从IMAP获取: {e}")
        
        # 2. 缓存不存在，先缓存邮件（不含附件）
        try:
            cache_path = self.fetch_and_cache_email_without_attachments(db, email_record)
            
            # 3. 从缓存读取内容
            with open(cache_path, 'rb') as f:
                raw_email = f.read()
            msg = email.message_from_bytes(raw_email)
            return self._parse_email_content(msg)
            
        except Exception as e:
            logger.error(f"获取邮件内容失败: {e}", exc_info=True)
            raise HTTPException(
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"获取邮件内容失败: {e}"
            )
    
    def _parse_email_content(self, msg: email.message.Message):
        """
        解析邮件内容（从email.message对象）
        返回：(text_body, html_body, inline_images_dict)
        """
        text_body = ""
        html_body = ""
        inline_images = {}
        
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))
                content_id = part.get("Content-ID")
                
                # 跳过附件
                if "attachment" in content_disposition:
                    continue
                
                # 提取正文
                if content_type == "text/html" and not html_body:
                    try:
                        payload = part.get_payload(decode=True)
                        charset = part.get_content_charset() or 'utf-8'
                        html_body = payload.decode(charset, errors='ignore')
                    except Exception as e:
                        logger.error(f"解码HTML正文失败: {e}")
                
                elif content_type == "text/plain" and not text_body:
                    try:
                        payload = part.get_payload(decode=True)
                        charset = part.get_content_charset() or 'utf-8'
                        text_body = payload.decode(charset, errors='ignore')
                    except Exception as e:
                        logger.error(f"解码文本正文失败: {e}")
                
                # 提取内嵌图片
                if content_id and "attachment" not in content_disposition:
                    cid = content_id.strip("<>")
                    try:
                        image_data = part.get_payload(decode=True)
                        inline_images[cid] = {
                            "data": image_data,
                            "type": part.get_content_type()
                        }
                    except Exception as e:
                        logger.error(f"提取内嵌图片失败: {e}")
        else:
            content_type = msg.get_content_type()
            try:
                payload = msg.get_payload(decode=True)
                charset = msg.get_content_charset() or 'utf-8'
                if content_type == "text/html":
                    html_body = payload.decode(charset, errors='ignore')
                else:
                    text_body = payload.decode(charset, errors='ignore')
            except Exception as e:
                logger.error(f"解码邮件正文失败: {e}")
        
        return text_body, html_body, inline_images
    
    def fetch_email_attachments_info(self, db: Session, email_record: Email):
        """
        获取邮件的附件信息列表（不下载附件内容）
        返回：[{index, filename, size, content_type}, ...]
        """
        logger.debug(f"获取邮件 {email_record.id} 的附件列表")
        
        try:
            self._connect()
            
            original_folder_name = self._get_original_folder_name(email_record.folder)
            select_status, select_data = self.imap.select(f'"{original_folder_name}"', readonly=True)
            if select_status != 'OK':
                raise ConnectionError(f"无法选择文件夹")
            
            uid_str = str(email_record.uid)
            
            # 获取邮件结构（不包含内容）
            fetch_status, msg_data = self.imap.uid('fetch', uid_str, '(BODY.PEEK[])')
            
            if fetch_status != 'OK' or not msg_data or msg_data[0] is None:
                raise ConnectionError(f"无法获取邮件数据")
            
            if not isinstance(msg_data[0], tuple) or len(msg_data[0]) < 2:
                raise ConnectionError(f"邮件数据结构异常")
            
            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)
            
            attachments = []
            attachment_index = 0
            
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition"))
                    content_id = part.get("Content-ID")
                    
                    # 识别附件
                    is_attachment = False
                    if "attachment" in content_disposition:
                        is_attachment = True
                    elif content_type not in ["text/plain", "text/html", "multipart/mixed", 
                                             "multipart/alternative", "multipart/related"] and not content_id:
                        is_attachment = True
                    
                    if is_attachment:
                        filename = part.get_filename()
                        if filename:
                            # 解码文件名
                            from email.header import decode_header
                            decoded_filename = decode_header(filename)[0]
                            if isinstance(decoded_filename[0], bytes):
                                filename = decoded_filename[0].decode(decoded_filename[1] or 'utf-8', errors='ignore')
                            else:
                                filename = decoded_filename[0]
                            
                            # 获取附件大小（通过获取payload）
                            payload = part.get_payload(decode=True)
                            size = len(payload) if payload else 0
                            
                            attachments.append({
                                "index": attachment_index,
                                "filename": filename,
                                "size": size,
                                "content_type": content_type
                            })
                            attachment_index += 1
            
            return attachments
            
        except Exception as e:
            logger.error(f"获取附件信息失败: {e}", exc_info=True)
            raise HTTPException(
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"获取附件信息失败: {e}"
            )
        finally:
            self._disconnect()
    
    def fetch_single_attachment(self, db: Session, email_record: Email, attachment_index: int):
        """
        按需获取单个附件
        返回：(filename, content_type, data)
        """
        logger.debug(f"按需下载邮件 {email_record.id} 的附件 #{attachment_index}")
        
        try:
            self._connect()
            
            original_folder_name = self._get_original_folder_name(email_record.folder)
            select_status, select_data = self.imap.select(f'"{original_folder_name}"', readonly=True)
            if select_status != 'OK':
                raise ConnectionError(f"无法选择文件夹")
            
            uid_str = str(email_record.uid)
            
            # 获取完整邮件用于解析附件
            fetch_status, msg_data = self.imap.uid('fetch', uid_str, '(BODY.PEEK[])')
            
            if fetch_status != 'OK' or not msg_data or msg_data[0] is None:
                raise ConnectionError(f"无法获取邮件数据")
            
            if not isinstance(msg_data[0], tuple) or len(msg_data[0]) < 2:
                raise ConnectionError(f"邮件数据结构异常")
            
            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)
            
            # 查找指定索引的附件
            current_index = 0
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition"))
                    content_id = part.get("Content-ID")
                    
                    # 识别附件
                    is_attachment = False
                    if "attachment" in content_disposition:
                        is_attachment = True
                    elif content_type not in ["text/plain", "text/html", "multipart/mixed", 
                                             "multipart/alternative", "multipart/related"] and not content_id:
                        is_attachment = True
                    
                    if is_attachment:
                        filename = part.get_filename()
                        if filename:
                            if current_index == attachment_index:
                                # 解码文件名
                                from email.header import decode_header
                                decoded_filename = decode_header(filename)[0]
                                if isinstance(decoded_filename[0], bytes):
                                    filename = decoded_filename[0].decode(decoded_filename[1] or 'utf-8', errors='ignore')
                                else:
                                    filename = decoded_filename[0]
                                
                                # 获取附件数据
                                payload = part.get_payload(decode=True)
                                
                                return filename, content_type, payload
                            
                            current_index += 1
            
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"未找到附件 #{attachment_index}"
            )
            
        except Exception as e:
            logger.error(f"下载附件失败: {e}", exc_info=True)
            raise HTTPException(
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"下载附件失败: {e}"
            )
        finally:
            self._disconnect()

    def fetch_emails_from_folder(self, folder: str, skip: int, limit: int):
        emails = []
        total = 0
        try:
            self._connect()
            self.imap.select(f'"{folder}"', readonly=True)
            
            status, uids_data = self.imap.uid('search', None, "ALL")
            if status == 'OK':
                uids = uids_data[0].split()
                total = len(uids)
                
                uids.reverse()
                
                paginated_uids = uids[skip : skip + limit]
                
                for uid in paginated_uids:
                    status, msg_data = self.imap.uid('fetch', uid, '(FLAGS BODY[HEADER.FIELDS (SUBJECT FROM TO DATE MESSAGE-ID)])')
                    
                    if status == 'OK':
                        import re
                        from email.parser import HeaderParser
                        
                        flags_part = msg_data[0][0].decode('utf-8')
                        flags_match = re.search(r'FLAGS \((.*?)\)', flags_part)
                        flags = flags_match.group(1).split() if flags_match else []
                        is_read = '\\Seen' in flags
                        
                        parser = HeaderParser()
                        headers = parser.parsestr(msg_data[0][1].decode('utf-8'))
                        
                        emails.append({
                            "id": int(uid),
                            "uid": uid.decode(),
                            "subject": headers['Subject'],
                            "sender": headers['From'],
                            "recipients": headers['To'],
                            "received_date": headers['Date'],
                            "folder": folder,
                            "is_read": is_read,
                        })
            
            self._disconnect()
            
        except Exception as e:
            logger.error(f"从文件夹 {folder} 获取邮件失败: {e}")
            return [], 0
            
        return emails, total

    def _connect(self):
        try:
            if self.account.imap_ssl:
                # 使用更通用的SSL上下文，以提高兼容性
                context = ssl.create_default_context()
                self.imap = imaplib.IMAP4_SSL(self.account.imap_server, self.account.imap_port, ssl_context=context)
            else:
                self.imap = imaplib.IMAP4(self.account.imap_server, self.account.imap_port)
            
            self.imap.login(self.account.email, self.account.password)
        
        except imaplib.IMAP4.error as e:
            # 主要捕获认证失败等IMAP特定错误
            logger.error(f"IMAP认证或操作失败 for {self.account.email}: {e}")
            raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED, detail=f"IMAP登录失败: {e}")
        except socket.error as e:
            # 捕获网络连接层面的错误
            logger.error(f"网络连接错误 for {self.account.email}: {e}")
            raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"网络连接错误: {e}")
        except Exception as e:
            # 捕获其他所有未知异常
            logger.error(f"连接邮箱时发生未知错误 {self.account.email}: {e}")
            raise

    def _disconnect(self):
        if self.imap:
            self.imap.logout()

    def create_folder(self, folder_name: str, parent_folder: str = None) -> bool:
        """
        在IMAP服务器上创建新文件夹。
        """
        try:
            db: Session = SessionLocal()
            account = db.query(EmailAccount).filter(EmailAccount.id == self.account_id).first()
            if not account:
                return False
            self.account = account
            self._connect()
            
            full_folder_name = f"{parent_folder}/{folder_name}" if parent_folder else folder_name
            encoded_folder_name = encode_modified_utf7(full_folder_name)
            
            status, _ = self.imap.create(f'"{encoded_folder_name}"')
            
            self._disconnect()
            return status == 'OK'
        except Exception as e:
            logger.error(f"创建文件夹失败: {e}")
            return False
        finally:
            db.close()

    def rename_folder(self, old_folder_name: str, new_folder_name: str) -> bool:
        """
        在IMAP服务器上重命名文件夹，并更新数据库中的相关邮件。
        """
        db: Session = SessionLocal()
        try:
            account = db.query(EmailAccount).filter(EmailAccount.id == self.account_id).first()
            if not account:
                return False
            self.account = account
            self._connect()

            encoded_old_name = encode_modified_utf7(old_folder_name)
            # 确保新的父级文件夹名称部分也被编码
            path_parts = new_folder_name.split('/')
            encoded_parts = [encode_modified_utf7(part) for part in path_parts]
            encoded_new_name = '/'.join(encoded_parts)

            status, _ = self.imap.rename(f'"{encoded_old_name}"', f'"{encoded_new_name}"')

            self._disconnect()

            if status == 'OK':
                # 开启事务
                with db.begin_nested():
                    # 1. 精确更新父文件夹本身
                    db.query(Email).filter(
                        Email.email_account_id == self.account_id,
                        Email.folder == old_folder_name
                    ).update({"folder": new_folder_name}, synchronize_session=False)

                    # 2. 精确更新所有直接和间接子文件夹的路径
                    old_prefix = f"{old_folder_name}/"
                    new_prefix = f"{new_folder_name}/"
                    
                    # 使用 SQLAlchemy 的 `startswith` 来确保精确匹配
                    db.query(Email).filter(
                        Email.email_account_id == self.account_id,
                        Email.folder.startswith(old_prefix)
                    ).update({
                        "folder": func.concat(new_prefix, func.substring(Email.folder, len(old_prefix) + 1))
                    }, synchronize_session=False)

                db.commit()
                logger.info(f"文件夹 '{old_folder_name}' 已成功重命名为 '{new_folder_name}' 并更新了数据库。")
                return True
            else:
                logger.error(f"IMAP服务器未能重命名文件夹 '{old_folder_name}'。")
                return False
        except Exception as e:
            logger.error(f"重命名文件夹时发生异常: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    def _get_folders_to_sync(self):
        folders_to_sync = {}
        
        try:
            status, folder_list = self.imap.list()
            if status == 'OK':
                for folder_data in folder_list:
                    line_str = folder_data.decode('utf-8', 'ignore')
                    match = re.match(r'\((.*?)\)\s+"(.*?)"\s+"(.*)"', line_str)
                    if match:
                        flags, _, original_name = match.groups()
                        if "\\Noselect" not in flags:
                            decoded_name = decode_modified_utf7(original_name)
                            
                            # 添加特殊文件夹名称映射
                            # 记录原始名称以便后续反向查找
                            if r'\Sent' in flags:
                                decoded_name = "Sent"
                            elif r'\Junk' in flags:
                                decoded_name = "Junk"
                            elif r'\Trash' in flags:
                                decoded_name = "Trash"
                            
                            folders_to_sync[original_name] = {
                                "original": original_name, 
                                "decoded": decoded_name,
                                "flags": flags
                            }
        except Exception as e:
            logger.error(f"Could not retrieve folder list: {e}")
        
        return list(folders_to_sync.values())

    def _sync_folder_only(self, folder_info: dict, db: Session):
        """
        仅同步指定的单个文件夹（用于刷新按钮）
        这个方法会自动管理IMAP连接
        """
        try:
            self._connect()
            self._sync_folder(folder_info, db)
        except Exception as e:
            logger.error(f"同步文件夹 '{folder_info.get('decoded', 'unknown')}' 失败: {e}", exc_info=True)
            raise
        finally:
            self._disconnect()

    def _sync_folder(self, folder_info: dict, db: Session):
        original_folder_name = folder_info["original"]
        decoded_folder_name = folder_info["decoded"]
        
        status, data = self.imap.select(f'"{original_folder_name}"', readonly=True)
        if status != 'OK':
            return
        
        # 获取当前文件夹的UIDVALIDITY
        current_uidvalidity = None
        
        # 方法1: 从SELECT响应中解析
        for line in data:
            if isinstance(line, bytes):
                line_str = line.decode('utf-8', 'ignore')
                if 'UIDVALIDITY' in line_str:
                    match = re.search(r'UIDVALIDITY (\d+)', line_str)
                    if match:
                        current_uidvalidity = match.group(1)
                        break
        
        # 方法2: 如果方法1失败，尝试使用STATUS命令
        if not current_uidvalidity:
            try:
                status_result, status_data = self.imap.status(f'"{original_folder_name}"', '(UIDVALIDITY)')
                if status_result == 'OK' and status_data:
                    status_str = status_data[0].decode('utf-8', 'ignore')
                    match = re.search(r'UIDVALIDITY (\d+)', status_str)
                    if match:
                        current_uidvalidity = match.group(1)
            except Exception as e:
                logger.error(f"通过 STATUS 命令获取 UIDVALIDITY 失败: {e}")
        
        # 方法3: 如果以上方法都失败，使用文件夹名+账户ID的哈希作为稳定标识
        if not current_uidvalidity:
            # 使用文件夹名和账户ID生成一个稳定的伪UIDVALIDITY
            hash_input = f"{self.account.id}-{decoded_folder_name}".encode('utf-8')
            folder_hash = hashlib.md5(hash_input).hexdigest()[:8]
            current_uidvalidity = str(int(folder_hash, 16))
            logger.debug(f"为文件夹 '{decoded_folder_name}' 使用生成的 UIDVALIDITY: {current_uidvalidity}")
        
        logger.info(f"正在同步文件夹 '{decoded_folder_name}'，UIDVALIDITY: {current_uidvalidity}")
        
        # 检查数据库中是否有该文件夹的邮件，并获取其UIDVALIDITY
        existing_email = db.query(Email).filter(
            Email.email_account_id == self.account.id,
            Email.folder == decoded_folder_name
        ).first()
        
        uidvalidity_changed = False
        if existing_email and existing_email.uidvalidity:
            if existing_email.uidvalidity != current_uidvalidity:
                logger.error(f"UIDVALIDITY changed for folder '{decoded_folder_name}': {existing_email.uidvalidity} -> {current_uidvalidity}")
                uidvalidity_changed = True
        
        status, uids_data = self.imap.uid('search', None, "ALL")
        if status != 'OK':
            return
        
        server_uids = set(uids_data[0].split())

        # 从数据库获取当前文件夹下所有邮件的 UID、UIDVALIDITY 和 eml_path
        existing_emails_info = db.query(Email.uid, Email.uidvalidity, Email.eml_path, Email.message_id, Email.email_hash).filter(
            Email.email_account_id == self.account.id,
            Email.folder == decoded_folder_name
        ).all()
        
        existing_uids_map = {str(uid).encode(): (uidvalidity, eml_path, message_id, email_hash) 
                            for uid, uidvalidity, eml_path, message_id, email_hash in existing_emails_info}
        existing_uids = set(existing_uids_map.keys())

        # 如果UIDVALIDITY改变，需要重新关联邮件
        if uidvalidity_changed:
            logger.info(f"由于 UIDVALIDITY 变更，正在重新同步文件夹 '{decoded_folder_name}'")
            # 将所有现有邮件的UID设置为待更新状态
            # 我们将通过Message-ID或email_hash来重新匹配
            for uid in existing_uids:
                _, _, message_id, email_hash = existing_uids_map[uid]
                # 标记这些邮件需要重新匹配UID
            existing_uids = set()  # 清空现有UID集合，强制重新同步所有邮件

        # 找出服务器上不存在但数据库中存在的邮件 (UIDs)
        # 注意：只有在UIDVALIDITY未改变的情况下才执行删除操作
        if not uidvalidity_changed:
            uids_to_delete = existing_uids - server_uids
            if uids_to_delete:
                # 1. 删除对应的 .eml 文件
                for uid in uids_to_delete:
                    uidvalidity, eml_path, _, _ = existing_uids_map.get(uid)
                    if eml_path and os.path.exists(eml_path):
                        try:
                            os.remove(eml_path)
                            logger.debug(f"已删除过期的 .eml 文件: {eml_path}")
                        except OSError as e:
                            logger.error(f"删除文件 {eml_path} 时出错: {e}")
                
                # 2. 从数据库中批量删除记录
                uids_to_delete_decoded = [uid.decode() for uid in uids_to_delete]
                db.query(Email).filter(
                    Email.email_account_id == self.account.id,
                    Email.folder == decoded_folder_name,
                    Email.uid.in_(uids_to_delete_decoded)
                ).delete(synchronize_session=False)
                db.flush()
                logger.info(f"已从文件夹 '{decoded_folder_name}' 中删除 {len(uids_to_delete)} 条在服务器上不再存在的邮件记录")

        # 找出需要从服务器下载的新邮件 (UIDs)
        new_uids = list(server_uids - existing_uids)
        
        if new_uids:
            logger.info(f"同步文件夹 '{decoded_folder_name}': 发现 {len(new_uids)} 封新邮件")
        else:
            logger.info(f"文件夹 '{decoded_folder_name}' 没有新邮件需要同步")
            return
        
        # 使用优化器进行分批处理
        optimizer = EmailSyncOptimizer(batch_size=50, memory_threshold=80)
        batches = optimizer.split_into_batches(new_uids)
        
        total_batches = len(batches)
        logger.info(f"将 {len(new_uids)} 封邮件分成 {total_batches} 批处理")
        
        # 分批处理新邮件
        for batch_idx, batch_uids in enumerate(batches, 1):
            logger.info(f"正在处理第 {batch_idx}/{total_batches} 批，共 {len(batch_uids)} 封邮件")
            
            # 处理当前批次的邮件
            for uid in batch_uids:
                try:
                    email_data = self._fetch_and_process_email(uid, self.imap, decoded_folder_name, current_uidvalidity, db)
                    if email_data:
                        text_body = email_data.pop('text_body', None)
                        html_body = email_data.pop('html_body', None)
                        has_attachments = email_data.get('has_attachments', False)
                        attachment_count = email_data.pop('attachment_count', 0)
                        email_data["summary"] = self._create_summary(text_body, html_body, has_attachments, attachment_count)
                        email_data["folder"] = decoded_folder_name
                        email_data["is_read"] = '\\Seen' in email_data.pop('flags', [])
                        email_data["uidvalidity"] = current_uidvalidity
                        
                        # 保存到数据库
                        self._save_email_to_db(email_data, db, current_uidvalidity)
                        
                        # 清理临时变量
                        del text_body, html_body, email_data
                        
                except Exception as e:
                    # 单个邮件失败不影响其他邮件的同步
                    db.rollback()
                    logger.error(f"错误: 处理 UID 为 {uid.decode() if isinstance(uid, bytes) else uid} 的邮件失败: {e}")
            
            # 批次处理完成后提交数据库
            try:
                db.commit()
                logger.info(f"第 {batch_idx}/{total_batches} 批处理完成，已提交到数据库")
            except Exception as e:
                logger.error(f"提交第 {batch_idx} 批数据失败: {e}")
                db.rollback()
            
            # 检查并释放内存
            optimizer.check_and_release_memory()
            
            # 强制垃圾回收
            gc.collect()
        
        logger.info(f"文件夹 '{decoded_folder_name}' 同步完成，共处理 {len(new_uids)} 封新邮件")


    def _fetch_and_process_email(self, uid: bytes, imap_conn, folder: str = "", uidvalidity: str = "", db: Session = None):
        """
        获取邮件的元数据和正文预览。
        这个版本获取完整的邮件结构来正确解析内容和附件，但只处理正文部分以生成摘要。
        """
        fetch_command = '(FLAGS BODY.PEEK[])'  # 获取完整的邮件，以便正确解析
        try:
            status, msg_data = imap_conn.uid('fetch', uid, fetch_command)
            if status != 'OK' or not msg_data or msg_data[0] is None:
                return None
        except Exception as e:
            logger.error(f"获取 UID {uid.decode()} 的完整邮件失败: {e}")
            return None

        flags = []
        raw_email_data = None

        # 从响应中提取标记和原始邮件数据
        for part in msg_data:
            if isinstance(part, tuple):
                # 提取 FLAGS
                part_info = part[0].decode('utf-8', 'ignore')
                flags_match = re.search(r'FLAGS \((.*?)\)', part_info)
                if flags_match:
                    flags = flags_match.group(1).split()
                
                # 提取原始邮件数据
                if len(part) > 1 and isinstance(part[1], bytes):
                    raw_email_data = part[1]
                    break 
        
        if not raw_email_data:
             # 如果在元组中找不到，有时它作为列表中的一个独立项
            for part in msg_data:
                if isinstance(part, bytes):
                    raw_email_data = part
                    break

        if raw_email_data:
            try:
                msg = email.message_from_bytes(raw_email_data)
                
                # 解析元数据（现在附件检查会更准确）
                email_metadata = self._parse_email_metadata(msg, uid.decode(), folder, uidvalidity, db)
                
                if email_metadata:
                    email_metadata['flags'] = flags
                    
                    # 解析正文以生成摘要
                    text_body, html_body = self._get_email_body(msg)
                    
                    # 将正文添加到元数据中，以便后续处理
                    email_metadata['text_body'] = text_body
                    email_metadata['html_body'] = html_body
                
                return email_metadata
            except Exception as e:
                logger.error(f"解析 UID {uid.decode()} 的邮件失败: {e}")
                return None
        
        return None


    def _get_email_body(self, msg: email.message.Message):
        text_body = ""
        html_body = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                if "attachment" not in content_disposition:
                    if content_type == "text/plain" and not text_body:
                        try:
                            payload = part.get_payload(decode=True)
                            charset = part.get_content_charset() or 'utf-8'
                            text_body = payload.decode(charset, errors='ignore')
                        except Exception as e:
                            logger.error(f"解码文本部分时出错: {e}")
                    elif content_type == "text/html" and not html_body:
                        try:
                            payload = part.get_payload(decode=True)
                            charset = part.get_content_charset() or 'utf-8'
                            html_body = payload.decode(charset, errors='ignore')
                        except Exception as e:
                            logger.error(f"解码 HTML 部分时出错: {e}")
        else:
            content_type = msg.get_content_type()
            try:
                payload = msg.get_payload(decode=True)
                charset = msg.get_content_charset() or 'utf-8'
                if content_type == "text/plain":
                    text_body = payload.decode(charset, errors='ignore')
                elif content_type == "text/html":
                    html_body = payload.decode(charset, errors='ignore')
            except Exception as e:
                logger.error(f"解码非多部分邮件正文时出错: {e}")

        return text_body, html_body

    def _decode_header(self, header: str) -> str:
        if not header:
            return ""
        decoded_parts = decode_header(header)
        header_parts = []
        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                if not charset or charset.lower() == 'unknown-8bit':
                    try:
                        header_parts.append(part.decode('utf-8'))
                    except UnicodeDecodeError:
                        try:
                            header_parts.append(part.decode('gb18030'))
                        except UnicodeDecodeError:
                            header_parts.append(part.decode('latin-1', errors='ignore'))
                else:
                    try:
                        header_parts.append(part.decode(charset, errors='ignore'))
                    except (LookupError, UnicodeDecodeError):
                        try:
                            header_parts.append(part.decode('gb18030'))
                        except UnicodeDecodeError:
                            header_parts.append(part.decode('utf-8', errors='replace'))
            else:
                header_parts.append(part)
        return "".join(header_parts)

    def _create_summary(self, text_body, html_body, has_attachments=False, attachment_count=0):
        """
        生成邮件简介
        规则：
        1. 判断是否存在附件，如果存在附件在前面加上（X个附件）
        2. 邮件正文（不包括附件）>过滤Html标签->过滤常见无意义英文符号->截取前300个有效字符
        3. 两者相加
        """
        # 提取正文内容
        content = text_body if text_body else ""
        
        if html_body:
            soup = BeautifulSoup(html_body, "html.parser")
            for script_or_style in soup(["script", "style"]):
                script_or_style.decompose()
            content = soup.get_text()
        elif text_body and text_body.strip().startswith('<'):
            soup = BeautifulSoup(text_body, "html.parser")
            for script_or_style in soup(["script", "style"]):
                script_or_style.decompose()
            content = soup.get_text()

        # 过滤HTML标签（防御性处理）
        content = re.sub(r'<[^>]+>', '', content)
        content = html.unescape(content)

        # 过滤常见无意义英文符号
        content = re.sub(r'[.,!?;:\'"()\[\]{}<>/\\_—–-]', ' ', content)
        
        # 将多个连续空格替换为一个空格
        content = re.sub(r'\s+', ' ', content).strip()
        
        # 截取前300个有效字符
        body_summary = content[:300]
        
        # 如果有附件，在前面添加附件提示
        if has_attachments and attachment_count > 0:
            attachment_prefix = f"({attachment_count}个附件) "
            return attachment_prefix + body_summary
        
        return body_summary

    def _generate_deterministic_message_id(self, msg, uid):
        subject = self._decode_header(msg.get("Subject", ""))
        sender = self._decode_header(msg.get("From", ""))
        date = msg.get("Date", "")
        
        hash_input = f"{uid}-{subject}-{sender}-{date}".encode('utf-8')
        hash_output = hashlib.sha256(hash_input).hexdigest()
        
        return f"<{hash_output}@{self.account.email.split('@')[-1]}>"

    def _parse_email_metadata(self, msg: email.message.Message, uid: str, folder: str = "", uidvalidity: str = "", db: Session = None):
        # 解析邮件基本信息
        original_message_id = msg.get("Message-ID")
        sender = self._decode_header(msg.get("From", ""))
        subject = self._decode_header(msg.get("Subject", ""))
        recipients = self._decode_header(msg.get("To", ""))
        cc = self._decode_header(msg.get("Cc", ""))
        
        date_str = msg.get("Date", "")
        try:
            received_date = email.utils.parsedate_to_datetime(date_str)
        except Exception:
            received_date = datetime.utcnow()
            date_str = received_date.isoformat()

        # 使用新的三层唯一性保障方案
        message_id, is_generated, content_hash = ensure_message_id(
            message_id=original_message_id,
            sender_email=sender,
            recipients=recipients,
            subject=subject,
            date_str=date_str,
            folder=folder,
            uid=uid,
            db=db,
            email_account_id=self.account.id
        )

        # 生成IMAP位置key
        imap_key = generate_imap_key(folder, uid, uidvalidity) if folder and uidvalidity else ""

        # 正确判断是否有附件及附件数量
        has_attachments, attachment_count = self._check_has_attachments(msg)
        
        return {
            "email_account_id": self.account.id,
            "uid": uid,
            "message_id": message_id,
            "is_generated_message_id": is_generated,
            "email_hash": content_hash,  # 保持向后兼容
            "content_hash": content_hash,  # 新字段
            "imap_key": imap_key,  # 新字段
            "subject": subject,
            "sender": sender,
            "recipients": recipients,
            "cc": cc,
            "received_date": received_date,
            "has_attachments": has_attachments,
            "attachment_count": attachment_count,
            "summary": ""
        }

    def _check_has_attachments(self, msg: email.message.Message):
        """
        检查邮件是否包含真正的附件（不包括内嵌图片）
        返回：(has_attachments: bool, attachment_count: int)
        """
        if not msg.is_multipart():
            return False, 0
        
        attachment_count = 0
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))
            content_id = part.get("Content-ID")
            
            # 跳过纯文本和HTML正文部分
            if content_type in ["text/plain", "text/html", "multipart/mixed", "multipart/alternative", "multipart/related"]:
                continue
            
            # 如果有Content-Disposition且包含attachment，则是附件
            if "attachment" in content_disposition:
                filename = part.get_filename()
                if filename:  # 确保有文件名
                    attachment_count += 1
            # 如果不是内嵌图片（没有Content-ID），且有文件名，可能是附件
            elif not content_id:
                filename = part.get_filename()
                if filename:
                    attachment_count += 1
        
        return attachment_count > 0, attachment_count

    def _save_email_to_db(self, email_data: dict, db: Session, uidvalidity: str):
        """
        保存邮件到数据库，使用Message-ID或email_hash进行去重
        优先使用Message-ID，如果Message-ID是生成的，则同时检查email_hash
        """
        email_account_id = email_data["email_account_id"]
        message_id = email_data["message_id"]
        email_hash = email_data["email_hash"]
        folder = email_data["folder"]
        uid = email_data["uid"]
        is_generated = email_data.get("is_generated_message_id", False)
        
        # 查找已存在的邮件记录
        db_email = None
        
        # 策略1：优先通过Message-ID查找（适用于有原始Message-ID的邮件）
        # 注意：同一Message-ID可能在不同账户中存在（转发、群发等情况）
        if message_id:
            db_email = db.query(Email).filter(
                Email.email_account_id == email_account_id,
                Email.message_id == message_id
            ).first()
            
            if db_email:
                logger.debug(f"通过 Message-ID 找到现有邮件: {message_id}")
        
        # 策略2：如果没找到，通过email_hash查找（适用于无Message-ID或生成的Message-ID）
        if not db_email and email_hash:
            db_email = db.query(Email).filter(
                Email.email_account_id == email_account_id,
                Email.email_hash == email_hash
            ).first()
            
            if db_email:
                logger.debug(f"通过 email_hash 找到现有邮件: {email_hash[:16]}...")
        
        # 策略3：如果还没找到，检查同一文件夹+UID+UIDVALIDITY组合（处理UIDVALIDITY未改变的情况）
        if not db_email:
            db_email = db.query(Email).filter(
                Email.email_account_id == email_account_id,
                Email.folder == folder,
                Email.uid == uid,
                Email.uidvalidity == uidvalidity
            ).first()
            
            if db_email:
                logger.debug(f"通过文件夹+uid+uidvalidity 找到现有邮件: {folder}/{uid}")
        
        if db_email:
            # 更新现有邮件记录的所有基本信息
            db_email.folder = folder
            db_email.uid = uid
            db_email.uidvalidity = uidvalidity
            db_email.is_read = email_data.get("is_read", db_email.is_read)
            
            # 更新邮件主题、发件人、收件人等基本信息
            db_email.subject = email_data.get("subject", db_email.subject)
            db_email.sender = email_data.get("sender", db_email.sender)
            db_email.recipients = email_data.get("recipients", db_email.recipients)
            db_email.cc = email_data.get("cc", db_email.cc)
            db_email.received_date = email_data.get("received_date", db_email.received_date)
            db_email.summary = email_data.get("summary", db_email.summary)
            
            # 更新附件信息
            if "has_attachments" in email_data:
                new_has_attachments = email_data.get("has_attachments", False)
                if db_email.has_attachments != new_has_attachments:
                    db_email.has_attachments = new_has_attachments
            
            # 更新Message-ID
            if not db_email.message_id and message_id:
                db_email.message_id = message_id
                db_email.is_generated_message_id = is_generated
            
            # 更新email_hash
            if not db_email.email_hash and email_hash:
                db_email.email_hash = email_hash
        else:
            # 创建新邮件记录
            try:
                email_data["uidvalidity"] = uidvalidity
                new_email = Email(**email_data)
                db.add(new_email)
                db.flush()
            except Exception as e:
                # 如果插入失败（通常是唯一性约束），说明邮件已存在
                db.rollback()
                logger.error(f"插入邮件失败且无法找到重复记录 - Message-ID: {message_id}...")
                logger.error(f"UID: {uid}, Folder: {folder}, 错误: {str(e)}")

    def move_email(self, db: Session, email_id: int, current_folder: str, target_folder: str):
        """
        移动邮件到指定文件夹
        注意：虚拟文件夹（如UNREAD、STARRED等）不是真实的IMAP文件夹，不能作为目标文件夹
        """
        # 定义虚拟文件夹列表
        virtual_folders = ["UNREAD", "STARRED", "FLAGGED"]
        
        # 检查目标文件夹是否为虚拟文件夹
        if target_folder.upper() in virtual_folders:
            raise HTTPException(
                status_code=400, 
                detail=f"无法移动邮件到虚拟文件夹 '{target_folder}'。虚拟文件夹是通过筛选条件显示的邮件集合，而非真实的服务器文件夹。"
            )
        
        try:
            # 获取邮件记录
            email_record = db.query(Email).filter(Email.id == email_id).first()
            if not email_record:
                raise HTTPException(status_code=404, detail="未找到邮件")

            # 检查源文件夹是否为虚拟文件夹
            actual_current_folder = current_folder
            if current_folder.upper() in virtual_folders:
                # 如果源文件夹是虚拟文件夹，使用邮件的真实文件夹
                actual_current_folder = email_record.folder
                logger.info(f"源文件夹 '{current_folder}' 是虚拟文件夹，使用真实文件夹: {actual_current_folder}")

            self._connect()
            
            # 获取源文件夹和目标文件夹在服务器上的真实名称（已编码）
            original_current_folder = self._get_original_folder_name(actual_current_folder)
            original_target_folder = self._get_original_folder_name(target_folder)
            
            logger.debug(f"源文件夹: {actual_current_folder} -> {original_current_folder}")
            logger.debug(f"目标文件夹: {target_folder} -> {original_target_folder}")
            
            # 验证目标文件夹是否存在
            if original_target_folder == target_folder:
                # 检查文件夹是否真的存在
                status, folder_list = self.imap.list()
                folder_exists = False
                if status == 'OK':
                    for folder_data in folder_list:
                        line_str = folder_data.decode('utf-8', 'ignore')
                        match = re.match(r'\((.*?)\)\s+"(.*?)"\s+"(.*)"', line_str)
                        if match:
                            _, _, folder_name = match.groups()
                            decoded_name = decode_modified_utf7(folder_name)
                            if decoded_name == target_folder:
                                folder_exists = True
                                original_target_folder = folder_name
                                break
                
                # 如果文件夹不存在，直接返回错误
                if not folder_exists:
                    raise HTTPException(
                        status_code=404, 
                        detail=f"目标文件夹 '{target_folder}' 在邮件服务器上不存在，请刷新文件夹列表后重试"
                    )
            
            # 选择源文件夹（使用服务器上的真实名称）
            logger.debug(f"正在选择源文件夹: {original_current_folder}")
            status, select_response = self.imap.select(f'"{original_current_folder}"', readonly=False)
            if status != 'OK':
                raise HTTPException(
                    status_code=500, 
                    detail=f"无法选择源文件夹 '{actual_current_folder}': {select_response}"
                )

            # 使用服务器上的真实文件夹名称进行 COPY
            
            # 确保UID是字符串格式
            uid_str = str(email_record.uid)
            logger.debug(f"正在将邮件 UID {uid_str} 从 '{actual_current_folder}' 复制到 '{target_folder}'...")
            logger.debug(f"使用服务器文件夹名称: {original_target_folder}")
            
            # 1. 复制邮件（使用服务器上的真实文件夹名称）
            result, copy_response = self.imap.uid('COPY', uid_str, f'"{original_target_folder}"')
            if result != 'OK':
                error_msg = f"无法复制邮件到 '{target_folder}': {copy_response}"
                logger.error(f"错误: {error_msg}")
                raise HTTPException(status_code=500, detail=error_msg)
            logger.info(f"成功复制邮件到 '{target_folder}'")

            # 2. 在原文件夹中标记为删除
            logger.debug(f"正在标记原邮件为删除...")
            result, store_response = self.imap.uid('STORE', uid_str, '+FLAGS', '(\\Deleted)')
            if result != 'OK':
                logger.error(f"警告: 标记邮件删除失败: {store_response}")

            # 3. 执行 expunge
            logger.debug(f"正在清理已删除邮件...")
            self.imap.expunge()

            # 4. 在目标文件夹中查找新的UID
            logger.debug(f"正在获取邮件在新文件夹中的UID...")
            new_uid = None
            try:
                # 选择目标文件夹
                status, _ = self.imap.select(f'"{original_target_folder}"', readonly=True)
                if status == 'OK':
                    # 使用Message-ID搜索邮件
                    message_id = email_record.message_id
                    if message_id:
                        # 清理Message-ID（移除可能的<>符号）
                        clean_message_id = message_id.strip('<>')
                        search_query = f'HEADER Message-ID "{clean_message_id}"'
                        status, data = self.imap.uid('search', None, search_query)
                        
                        if status == 'OK' and data[0]:
                            uids = data[0].split()
                            if uids:
                                new_uid = uids[0].decode()
                                logger.info(f"在目标文件夹中找到新UID: {new_uid}")
                            else:
                                logger.error(f"通过Message-ID未找到邮件，将尝试其他方法")
                        else:
                            logger.error(f"搜索失败: {data}")
                    
                    # 如果通过Message-ID没找到，尝试通过主题和发件人搜索
                    if not new_uid:
                        logger.debug(f"尝试通过主题和发件人搜索...")
                        status, all_uids_data = self.imap.uid('search', None, "ALL")
                        if status == 'OK' and all_uids_data[0]:
                            all_uids = all_uids_data[0].split()
                            # 只检查最近的几封邮件（刚复制的应该在最后）
                            recent_uids = all_uids[-10:] if len(all_uids) > 10 else all_uids
                            
                            for check_uid in reversed(recent_uids):
                                status, msg_data = self.imap.uid('fetch', check_uid, '(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM)])')
                                if status == 'OK' and msg_data[0]:
                                    header_data = msg_data[0][1]
                                    msg = email.message_from_bytes(header_data)
                                    fetched_subject = self._decode_header(msg.get("Subject", ""))
                                    fetched_sender = self._decode_header(msg.get("From", ""))
                                    
                                    if fetched_subject == email_record.subject and fetched_sender == email_record.sender:
                                        new_uid = check_uid.decode()
                                        logger.info(f"通过主题和发件人匹配找到新UID: {new_uid}")
                                        break
            except Exception as e:
                logger.error(f"获取新UID失败: {e}")

            # 5. 更新数据库
            email_record.folder = target_folder
            if new_uid:
                email_record.uid = new_uid
                logger.info(f"已更新邮件UID: {uid_str} -> {new_uid}")
            else:
                logger.error(f"未能获取新UID，保留旧UID: {uid_str}")
            
            db.commit()
            logger.info(f"成功移动邮件 {email_id} 从 '{actual_current_folder}' 到 '{target_folder}'")

        except HTTPException:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
            error_msg = f"移动邮件时发生错误: {str(e)}"
            logger.error(error_msg)
            raise HTTPException(status_code=500, detail=error_msg)
        finally:
            self._disconnect()
