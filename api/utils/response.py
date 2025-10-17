from typing import Any, Optional

def success(data: Any = None, msg: str = "操作成功", count: Optional[int] = None):
    response = {
        "success": True,
        "msg": msg,
        "data": data
    }
    if count is not None:
        response["count"] = count
    return response

def fail(msg: str = "操作失败", data: Any = None):
    return {
        "success": False,
        "msg": msg,
        "data": data
    }
