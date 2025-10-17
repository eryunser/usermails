from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from datetime import datetime, timedelta
from jose import jwt
from api.controller.auth import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
from api.utils.logger import get_logger

logger = get_logger("jwt_middleware")

class JWTRefreshMiddleware(BaseHTTPMiddleware):
    """JWT自动续期中间件
    
    当token剩余有效期少于总有效期的50%时，自动生成新token并通过响应头返回
    """
    
    # 续期阈值：当剩余时间少于总时间的50%时触发续期
    REFRESH_THRESHOLD = 0.5
    
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # 只处理成功的请求
        if response.status_code == 200:
            # 获取Authorization头
            auth_header = request.headers.get('Authorization')
            if auth_header and auth_header.startswith('Bearer '):
                token = auth_header.split(' ')[1]
                
                try:
                    # 解码token
                    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
                    exp = payload.get('exp')
                    
                    if exp:
                        # 计算剩余有效时间
                        now = datetime.utcnow()
                        exp_datetime = datetime.fromtimestamp(exp)
                        remaining_time = (exp_datetime - now).total_seconds()
                        
                        # 计算总有效时间和续期阈值
                        total_time = ACCESS_TOKEN_EXPIRE_MINUTES * 60
                        threshold_time = total_time * self.REFRESH_THRESHOLD
                        
                        # 如果剩余时间少于阈值且token仍然有效，生成新token
                        if 0 < remaining_time < threshold_time:
                            # 生成新token
                            new_expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
                            new_payload = {
                                "sub": payload.get("sub"),
                                "exp": new_expire
                            }
                            new_token = jwt.encode(new_payload, SECRET_KEY, algorithm=ALGORITHM)
                            
                            # 在响应头中添加新token
                            response.headers['X-New-Token'] = new_token
                            
                            # 记录续期日志
                            username = payload.get("sub")
                            remaining_hours = remaining_time / 3600
                            logger.info(f"Token自动续期: 用户={username}, 剩余时间={remaining_hours:.2f}小时")
                            
                except jwt.ExpiredSignatureError:
                    # token已过期，不处理
                    pass
                except jwt.JWTError as e:
                    # token解码失败，不处理
                    logger.debug(f"JWT解码失败: {str(e)}")
                except Exception as e:
                    # 其他错误，记录但不影响响应
                    logger.error(f"JWT续期中间件错误: {str(e)}")
        
        return response
