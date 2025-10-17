"""
基于文件的缓存工具
类似Redis的接口设计，支持键值对存储、过期时间等功能
"""
import os
import json
import time
import hashlib
from typing import Any, Optional
from datetime import datetime, timedelta
from pathlib import Path
from api.utils.logger import get_logger

# 初始化日志
logger = get_logger("cache")


class FileCache:
    """基于文件的缓存工具类"""
    
    def __init__(self, cache_dir: str = "api/runtime/cache"):
        """
        初始化缓存
        
        Args:
            cache_dir: 缓存目录路径
        """
        self.cache_dir = cache_dir
        # 确保缓存目录存在
        os.makedirs(cache_dir, exist_ok=True)
    
    def _get_cache_path(self, key: str) -> str:
        """
        获取缓存文件路径
        
        Args:
            key: 缓存键
            
        Returns:
            缓存文件的完整路径
        """
        # 使用MD5哈希避免文件名过长或包含非法字符
        key_hash = hashlib.md5(key.encode('utf-8')).hexdigest()
        return os.path.join(self.cache_dir, f"{key_hash}.cache")
    
    def set(self, key: str, value: Any, expire: Optional[int] = None) -> bool:
        """
        设置缓存
        
        Args:
            key: 缓存键
            value: 缓存值（会被JSON序列化）
            expire: 过期时间（秒），None表示永不过期
            
        Returns:
            是否设置成功
        """
        try:
            cache_path = self._get_cache_path(key)
            
            # 计算过期时间戳
            expire_time = None
            if expire is not None:
                expire_time = time.time() + expire
            
            # 构建缓存数据
            cache_data = {
                "key": key,  # 保存原始key用于调试
                "value": value,
                "expire_time": expire_time,
                "created_at": time.time()
            }
            
            # 写入文件
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            logger.error(f"[FileCache] 设置缓存失败 - key: {key}, error: {e}")
            return False
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取缓存
        
        Args:
            key: 缓存键
            default: 默认值（当缓存不存在或已过期时返回）
            
        Returns:
            缓存值或默认值
        """
        try:
            cache_path = self._get_cache_path(key)
            
            # 检查文件是否存在
            if not os.path.exists(cache_path):
                return default
            
            # 读取缓存文件
            with open(cache_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            # 检查是否过期
            expire_time = cache_data.get("expire_time")
            if expire_time is not None and time.time() > expire_time:
                # 已过期，删除缓存文件
                self.delete(key)
                return default
            
            return cache_data.get("value", default)
        except Exception as e:
            logger.error(f"[FileCache] 获取缓存失败 - key: {key}, error: {e}")
            return default
    
    def exists(self, key: str) -> bool:
        """
        检查缓存是否存在且未过期
        
        Args:
            key: 缓存键
            
        Returns:
            是否存在
        """
        try:
            cache_path = self._get_cache_path(key)
            
            if not os.path.exists(cache_path):
                return False
            
            # 读取缓存检查过期时间
            with open(cache_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            expire_time = cache_data.get("expire_time")
            if expire_time is not None and time.time() > expire_time:
                # 已过期
                self.delete(key)
                return False
            
            return True
        except Exception as e:
            logger.error(f"[FileCache] 检查缓存存在性失败 - key: {key}, error: {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """
        删除缓存
        
        Args:
            key: 缓存键
            
        Returns:
            是否删除成功
        """
        try:
            cache_path = self._get_cache_path(key)
            
            if os.path.exists(cache_path):
                os.remove(cache_path)
                return True
            
            return False
        except Exception as e:
            logger.error(f"[FileCache] 删除缓存失败 - key: {key}, error: {e}")
            return False
    
    def clear(self, pattern: Optional[str] = None) -> int:
        """
        清空缓存
        
        Args:
            pattern: 可选的键前缀模式，如果提供则只删除匹配的缓存
            
        Returns:
            删除的缓存数量
        """
        try:
            count = 0
            
            # 遍历缓存目录
            for filename in os.listdir(self.cache_dir):
                if not filename.endswith('.cache'):
                    continue
                
                cache_path = os.path.join(self.cache_dir, filename)
                
                # 如果指定了模式，需要读取文件检查原始key
                if pattern is not None:
                    try:
                        with open(cache_path, 'r', encoding='utf-8') as f:
                            cache_data = json.load(f)
                            if not cache_data.get("key", "").startswith(pattern):
                                continue
                    except:
                        pass
                
                # 删除文件
                try:
                    os.remove(cache_path)
                    count += 1
                except:
                    pass
            
            return count
        except Exception as e:
            logger.error(f"[FileCache] 清空缓存失败 - error: {e}")
            return 0
    
    def expire(self, key: str, seconds: int) -> bool:
        """
        设置缓存的过期时间
        
        Args:
            key: 缓存键
            seconds: 过期时间（秒）
            
        Returns:
            是否设置成功
        """
        try:
            cache_path = self._get_cache_path(key)
            
            if not os.path.exists(cache_path):
                return False
            
            # 读取现有缓存
            with open(cache_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            # 更新过期时间
            cache_data["expire_time"] = time.time() + seconds
            
            # 写回文件
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            logger.error(f"[FileCache] 设置过期时间失败 - key: {key}, error: {e}")
            return False
    
    def ttl(self, key: str) -> Optional[int]:
        """
        获取缓存的剩余生存时间
        
        Args:
            key: 缓存键
            
        Returns:
            剩余秒数，-1表示永不过期，None表示不存在
        """
        try:
            cache_path = self._get_cache_path(key)
            
            if not os.path.exists(cache_path):
                return None
            
            # 读取缓存
            with open(cache_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            expire_time = cache_data.get("expire_time")
            if expire_time is None:
                return -1  # 永不过期
            
            remaining = int(expire_time - time.time())
            if remaining <= 0:
                # 已过期
                self.delete(key)
                return None
            
            return remaining
        except Exception as e:
            logger.error(f"[FileCache] 获取TTL失败 - key: {key}, error: {e}")
            return None
    
    def keys(self, pattern: Optional[str] = None) -> list:
        """
        获取所有缓存键
        
        Args:
            pattern: 可选的键前缀模式
            
        Returns:
            缓存键列表
        """
        try:
            keys = []
            
            for filename in os.listdir(self.cache_dir):
                if not filename.endswith('.cache'):
                    continue
                
                cache_path = os.path.join(self.cache_dir, filename)
                
                try:
                    with open(cache_path, 'r', encoding='utf-8') as f:
                        cache_data = json.load(f)
                        key = cache_data.get("key", "")
                        
                        # 检查是否过期
                        expire_time = cache_data.get("expire_time")
                        if expire_time is not None and time.time() > expire_time:
                            continue
                        
                        # 检查模式匹配
                        if pattern is None or key.startswith(pattern):
                            keys.append(key)
                except:
                    pass
            
            return keys
        except Exception as e:
            logger.error(f"[FileCache] 获取键列表失败 - error: {e}")
            return []
    
    def cleanup_expired(self) -> int:
        """
        清理所有过期的缓存
        
        Returns:
            清理的缓存数量
        """
        try:
            count = 0
            
            for filename in os.listdir(self.cache_dir):
                if not filename.endswith('.cache'):
                    continue
                
                cache_path = os.path.join(self.cache_dir, filename)
                
                try:
                    with open(cache_path, 'r', encoding='utf-8') as f:
                        cache_data = json.load(f)
                    
                    expire_time = cache_data.get("expire_time")
                    if expire_time is not None and time.time() > expire_time:
                        os.remove(cache_path)
                        count += 1
                except:
                    pass
            
            return count
        except Exception as e:
            logger.error(f"[FileCache] 清理过期缓存失败 - error: {e}")
            return 0


# 创建全局缓存实例
cache = FileCache()
