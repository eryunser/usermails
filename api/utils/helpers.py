import base64
import hashlib
import uuid
import re
import time
from urllib.parse import unquote
from email.utils import parseaddr
from typing import Optional
from sqlalchemy.orm import Session
from api.utils.logger import get_logger

# 初始化日志
logger = get_logger("helpers")

def decode_url_encoded_str(s: str) -> str:
    """
    Decodes a URL-encoded string.
    """
    return unquote(s)

def decode_modified_utf7(s: str) -> str:
    """
    Decodes a string from IMAP's modified UTF-7 encoding.
    """
    if '&' not in s:
        return s
    
    parts = []
    encoded_blocks = s.split('&')
    parts.append(encoded_blocks[0])
    
    for block in encoded_blocks[1:]:
        if not block:
            parts.append('&')
            continue
        
        try:
            dash_index = block.find('-')
            if dash_index == -1:
                parts.append('&' + block)
                continue

            b64_part = block[:dash_index]
            rest = block[dash_index+1:]

            if not b64_part:
                parts.append('&' + rest)
                continue

            b64_part = b64_part.replace(',', '/')
            padded_b64 = b64_part + '==='
            decoded_bytes = base64.b64decode(padded_b64)
            parts.append(decoded_bytes.decode('utf-16-be'))
            parts.append(rest)
        except Exception:
            parts.append('&' + block)
            
    return "".join(parts)

def encode_modified_utf7(s: str) -> str:
    """
    Encodes a string to IMAP's modified UTF-7 encoding.
    """
    res = ""
    current_utf16 = ""
    for char in s:
        if ' ' <= char <= '~':
            if current_utf16:
                res += "&" + base64.b64encode(current_utf16.encode('utf-16-be')).decode('ascii').rstrip("=") + "-"
                current_utf16 = ""
            if char == '&':
                res += "&-"
            else:
                res += char
        else:
            current_utf16 += char
    if current_utf16:
        res += "&" + base64.b64encode(current_utf16.encode('utf-16-be')).decode('ascii').rstrip("=") + "-"
    return res

def normalize_email_address(email_str: str) -> str:
    """
    标准化邮件地址，提取纯邮箱地址并转小写
    例如: "张三 <zhangsan@example.com>" -> "zhangsan@example.com"
    """
    if not email_str:
        return ""
    name, addr = parseaddr(email_str)
    return addr.lower().strip()

def normalize_email_addresses(email_str: str) -> str:
    """
    标准化多个邮件地址，按字母顺序排序后合并
    用于To、Cc等可能包含多个收件人的字段
    """
    if not email_str:
        return ""
    # 分割多个邮件地址（可能用逗号、分号分隔）
    addresses = re.split(r'[,;]\s*', email_str)
    normalized = [normalize_email_address(addr) for addr in addresses if addr.strip()]
    # 排序并用逗号连接
    return ",".join(sorted(normalized))

def normalize_subject(subject: str) -> str:
    """
    标准化邮件主题，去除Re:、Fwd:等前缀
    """
    if not subject:
        return ""
    # 去除常见的回复/转发前缀（支持中英文）
    subject = re.sub(r'^(Re|RE|re|Fwd|FWD|fwd|回复|转发|答复):\s*', '', subject, flags=re.IGNORECASE)
    return subject.strip()

def generate_content_hash(sender: str, recipients: str, subject: str, date_str: str) -> str:
    """
    生成内容确定性哈希（完整64位SHA256）
    
    参数:
        sender: 发件人
        recipients: 收件人
        subject: 邮件主题
        date_str: 邮件日期字符串
    
    返回:
        64位十六进制哈希字符串
    """
    # 标准化各个字段
    normalized_sender = normalize_email_address(sender)
    normalized_recipients = normalize_email_addresses(recipients)
    normalized_subject = normalize_subject(subject)
    
    # 组合字段，使用固定分隔符
    combined = f"{normalized_sender}|{normalized_recipients}|{normalized_subject}|{date_str}"
    
    # 计算完整SHA256哈希
    return hashlib.sha256(combined.encode('utf-8')).hexdigest()


def generate_email_hash(sender: str, recipients: str, subject: str, date_str: str) -> str:
    """
    兼容旧接口：基于邮件元数据生成SHA256哈希值
    （保持向后兼容，实际调用generate_content_hash）
    """
    return generate_content_hash(sender, recipients, subject, date_str)

def generate_imap_key(folder: str, uid: str, uidvalidity: str) -> str:
    """
    生成IMAP位置唯一标识
    
    参数:
        folder: 文件夹名
        uid: 邮件UID
        uidvalidity: 文件夹UIDVALIDITY
    
    返回:
        格式化的IMAP key: folder|uid|uidvalidity
    """
    return f"{folder}|{uid}|{uidvalidity}"


def _short_location_id(folder: str, uid: str) -> str:
    """
    生成6字符位置标识（用于Message-ID后缀）
    
    参数:
        folder: 文件夹名
        uid: 邮件UID
    
    返回:
        6字符位置标识，例如: a1b045
    """
    folder_hash = hashlib.md5(folder.encode()).hexdigest()[:3]
    uid_part = f"{int(uid) % 1000:03d}"
    return f"{folder_hash}{uid_part}"


def check_content_conflict(
    db: Session,
    content_hash: str,
    email_account_id: int,
    folder: str,
    uid: str
) -> bool:
    """
    检测内容指纹是否可能冲突
    仅当存在多个位置使用相同内容时触发
    
    参数:
        db: 数据库会话
        content_hash: 内容哈希
        email_account_id: 邮箱账户ID
        folder: 当前文件夹
        uid: 当前UID
    
    返回:
        True表示存在冲突，False表示无冲突
    """
    from api.model.email import Email
    from sqlalchemy import func
    
    # 查询相同内容但不同位置的记录数
    count = db.query(func.count(Email.id)).filter(
        Email.content_hash == content_hash,
        Email.email_account_id == email_account_id
    ).scalar()
    
    # 如果已有记录，新邮件会构成冲突
    return count >= 1


def generate_content_based_message_id(
    sender: str,
    recipients: str,
    subject: str,
    date_str: str,
    folder: str,
    uid: str,
    db: Optional[Session] = None,
    email_account_id: Optional[int] = None
) -> tuple[str, str]:
    """
    生成基于内容的确定性Message-ID（三层唯一性保障）
    
    参数:
        sender: 发件人
        recipients: 收件人
        subject: 邮件主题
        date_str: 邮件日期字符串
        folder: 文件夹名
        uid: 邮件UID
        db: 数据库会话（可选，用于冲突检测）
        email_account_id: 邮箱账户ID（可选，用于冲突检测）
    
    返回:
        (message_id, content_hash) 元组
        - message_id: 生成的Message-ID
        - content_hash: 完整内容哈希
    """
    # 生成内容哈希
    content_hash = generate_content_hash(sender, recipients, subject, date_str)
    
    # 基础指纹（取前24位）
    base_fingerprint = content_hash[:24]
    
    # 提取域名
    domain = sender.split('@')[-1] if '@' in sender else 'content-hash'
    
    # 默认无后缀
    location_suffix = ""
    
    # 仅当提供数据库会话且检测到冲突时添加位置标识
    if db and email_account_id:
        if check_content_conflict(db, content_hash, email_account_id, folder, uid):
            # 添加位置后缀以区分相同内容的不同邮件
            location_suffix = f".{_short_location_id(folder, uid)}"
            logger.debug(f"检测到内容冲突，添加位置后缀: {location_suffix}")
    
    message_id = f"<{base_fingerprint}{location_suffix}@{domain}>"
    
    return message_id, content_hash


def generate_message_id(domain: str) -> str:
    """
    生成随机UUID类型的Message-ID（用于发送邮件）
    
    参数:
        domain: 邮件域名（从邮箱地址中提取）
    
    返回:
        格式化的Message-ID字符串，如: <uuid@domain>
    """
    unique_id = uuid.uuid4().hex
    return f"<{unique_id}@{domain}>"


def ensure_message_id(
    message_id: str,
    sender_email: str,
    recipients: str = "",
    subject: str = "",
    date_str: str = "",
    folder: str = "",
    uid: str = "",
    db: Optional[Session] = None,
    email_account_id: Optional[int] = None
) -> tuple[str, bool, str]:
    """
    确保邮件有Message-ID，如果没有则生成基于内容的确定性ID
    
    参数:
        message_id: 原始Message-ID（可能为None）
        sender_email: 发件人邮箱地址
        recipients: 收件人（用于生成内容ID）
        subject: 主题（用于生成内容ID）
        date_str: 日期字符串（用于生成内容ID）
        folder: 文件夹名（用于生成内容ID）
        uid: 邮件UID（用于生成内容ID）
        db: 数据库会话（可选，用于冲突检测）
        email_account_id: 邮箱账户ID（可选，用于冲突检测）
    
    返回:
        (message_id, is_generated, content_hash) 元组
        - message_id: 确保存在的Message-ID
        - is_generated: 布尔值，表示是否是系统生成的
        - content_hash: 内容哈希（64位完整哈希）
    """
    # 生成内容哈希（无论是否有原始Message-ID都生成）
    content_hash = generate_content_hash(sender_email, recipients, subject, date_str)
    
    # 如果有原始Message-ID，直接使用
    if message_id and message_id.strip():
        return message_id.strip(), False, content_hash
    
    # 如果有完整信息，生成基于内容的确定性ID
    if recipients and subject and date_str and folder and uid:
        generated_id, content_hash = generate_content_based_message_id(
            sender_email, recipients, subject, date_str, folder, uid, db, email_account_id
        )
        return generated_id, True, content_hash
    
    # 否则生成随机UUID类型的ID（兼容旧逻辑）
    domain = sender_email.split('@')[-1] if '@' in sender_email else 'localhost'
    generated_id = generate_message_id(domain)
    
    return generated_id, True, content_hash
