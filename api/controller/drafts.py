from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import datetime

from api.database import get_db
from api.model.user import User
from api.model.email_account import EmailAccount
from api.model.draft import Draft
from api.controller.auth import get_current_user
from api.schemas.email.draft import EmailDraft, EmailDraftResponse
from api.schemas.response import ApiResponse
from api.utils.response import success, fail

router = APIRouter()

@router.get("")
async def get_drafts(
    account_id: int,
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取草稿列表
    """
    try:
        account = db.query(EmailAccount).filter(
            EmailAccount.id == account_id,
            EmailAccount.user_id == current_user.id
        ).first()
        if not account:
            return fail("邮箱账户未找到")

        query = db.query(Draft).filter(Draft.email_account_id == account_id)
        total = query.count()
        drafts = query.order_by(Draft.updated_at.desc()).offset(skip).limit(limit).all()
        
        response_data = [
            {
                "id": draft.id,
                "email_account_id": draft.email_account_id,
                "subject": draft.subject,
                "recipients": draft.recipients,
                "sender": account.email,
                "is_read": True,
                "received_date": draft.updated_at,
                "folder": "Drafts",
            } for draft in drafts
        ]
        return success(response_data, count=total)
    except Exception as e:
        return fail(f"获取草稿列表失败: {str(e)}")

@router.get("/{draft_id}")
async def get_draft(
    account_id: int,
    draft_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取单封草稿详情
    """
    try:
        account = db.query(EmailAccount).filter(
            EmailAccount.id == account_id,
            EmailAccount.user_id == current_user.id
        ).first()
        if not account:
            return fail("邮箱账户未找到")
        
        draft = db.query(Draft).filter(
            Draft.id == draft_id,
            Draft.email_account_id == account_id
        ).first()
        
        if not draft:
            return fail("草稿未找到")
        
        return success(draft)
    except Exception as e:
        return fail(f"获取草稿详情失败: {str(e)}")

@router.post("")
async def save_draft(
    account_id: int,
    draft: EmailDraft,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    保存邮件草稿到 drafts 表
    """
    try:
        account = db.query(EmailAccount).filter(
            EmailAccount.id == account_id,
            EmailAccount.user_id == current_user.id
        ).first()
        if not account:
            return fail("邮箱账户未找到")

        if draft.id:
            # 更新现有草稿
            db_draft = db.query(Draft).filter(
                Draft.id == draft.id,
                Draft.email_account_id == account_id
            ).first()
            if not db_draft:
                return fail("草稿未找到")
            
            update_data = draft.dict(exclude_unset=True)
            for key, value in update_data.items():
                setattr(db_draft, key, value)
            
            db_draft.updated_at = datetime.utcnow()
            
        else:
            # 创建新草稿
            db_draft = Draft(
                email_account_id=account_id,
                subject=draft.subject or "无主题",
                recipients=draft.recipients or "",
                cc=draft.cc or "",
                body=draft.body or ""
            )
            db.add(db_draft)

        db.commit()
        db.refresh(db_draft)
        
        return success(data={"id": db_draft.id}, msg="草稿保存成功")
    except Exception as e:
        db.rollback()
        return fail(f"保存草稿失败: {str(e)}")

@router.delete("/{draft_id}")
async def delete_draft(
    account_id: int,
    draft_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    删除草稿
    """
    try:
        account = db.query(EmailAccount).filter(
            EmailAccount.id == account_id,
            EmailAccount.user_id == current_user.id
        ).first()
        if not account:
            return fail("邮箱账户未找到")
        
        draft_to_delete = db.query(Draft).filter(
            Draft.id == draft_id,
            Draft.email_account_id == account_id
        ).first()
        
        if not draft_to_delete:
            return fail("草稿未找到")
        
        db.delete(draft_to_delete)
        db.commit()
        return success(msg="草稿已删除")
    except Exception as e:
        db.rollback()
        return fail(f"删除草稿失败: {str(e)}")
