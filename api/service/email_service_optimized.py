import os
import gc
import psutil
from typing import List
from api.utils.logger import get_logger

logger = get_logger("email_service")

class EmailSyncOptimizer:
    """邮件同步优化器 - 分批处理和内存管理"""
    
    def __init__(self, batch_size=50, memory_threshold=80):
        """
        初始化优化器
        
        Args:
            batch_size: 每批处理的邮件数量（默认50封）
            memory_threshold: 内存使用阈值百分比（默认80%），超过此值会触发垃圾回收
        """
        self.batch_size = batch_size
        self.memory_threshold = memory_threshold
    
    def get_memory_usage(self) -> float:
        """获取当前内存使用百分比"""
        try:
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            # 获取系统总内存
            total_memory = psutil.virtual_memory().total
            # 计算使用百分比
            usage_percent = (memory_info.rss / total_memory) * 100
            return usage_percent
        except Exception as e:
            logger.error(f"获取内存使用情况失败: {e}")
            return 0.0
    
    def force_garbage_collection(self):
        """强制执行垃圾回收"""
        collected = gc.collect()
        logger.debug(f"强制垃圾回收完成，回收对象数: {collected}")
    
    def check_and_release_memory(self):
        """检查内存使用情况，必要时释放内存"""
        memory_usage = self.get_memory_usage()
        logger.debug(f"当前内存使用: {memory_usage:.2f}%")
        
        if memory_usage > self.memory_threshold:
            logger.warning(f"内存使用超过阈值 {self.memory_threshold}%，执行垃圾回收...")
            self.force_garbage_collection()
            
            # 再次检查
            new_usage = self.get_memory_usage()
            logger.info(f"垃圾回收后内存使用: {new_usage:.2f}%")
    
    def split_into_batches(self, items: List, batch_size: int = None) -> List[List]:
        """
        将列表分割成多个批次
        
        Args:
            items: 要分割的列表
            batch_size: 每批的大小，如果为None则使用默认值
        
        Returns:
            分批后的列表的列表
        """
        if batch_size is None:
            batch_size = self.batch_size
        
        batches = []
        for i in range(0, len(items), batch_size):
            batches.append(items[i:i + batch_size])
        
        return batches
    
    def adjust_batch_size_by_memory(self) -> int:
        """根据当前内存使用情况动态调整批次大小"""
        memory_usage = self.get_memory_usage()
        
        if memory_usage > 70:
            # 内存紧张，减小批次
            adjusted_size = max(10, self.batch_size // 2)
            logger.info(f"内存使用较高({memory_usage:.2f}%)，减小批次大小到 {adjusted_size}")
            return adjusted_size
        elif memory_usage < 40:
            # 内存充足，增大批次
            adjusted_size = min(100, self.batch_size * 2)
            logger.debug(f"内存充足({memory_usage:.2f}%)，增大批次大小到 {adjusted_size}")
            return adjusted_size
        else:
            return self.batch_size
