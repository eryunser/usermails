from pydantic import BaseModel
from typing import TypeVar, Generic, Optional

T = TypeVar('T')

class ApiResponse(BaseModel, Generic[T]):
    success: bool = True
    msg: str = "操作成功"
    data: Optional[T] = None
