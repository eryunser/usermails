"""
日志记录工具模块
提供统一的日志记录功能，支持按日期和级别分割日志文件
"""
import logging
import os
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

# 日志目录
LOG_DIR = Path(__file__).parent.parent / "runtime" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 日志格式
LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 全局logger字典，避免重复创建
_loggers = {}


class DailyRotatingFileHandler(TimedRotatingFileHandler):
    """
    按天分割的日志处理器，文件名格式：YYYYMMDD_level.log
    """
    def __init__(self, log_dir, level_name, when='midnight', interval=1, backup_count=30):
        """
        初始化日志处理器
        
        Args:
            log_dir: 日志目录
            level_name: 日志级别名称（debug/info/error）
            when: 分割时间单位，默认midnight（每天午夜）
            interval: 分割间隔，默认1天
            backup_count: 保留的日志文件数量，默认30天
        """
        self.log_dir = Path(log_dir)
        self.level_name = level_name.lower()
        
        # 生成当前日志文件名
        filename = self._generate_filename()
        
        super().__init__(
            filename=str(filename),
            when=when,
            interval=interval,
            backupCount=backup_count,
            encoding='utf-8'
        )
        
    def _generate_filename(self):
        """生成日志文件名：YYYYMMDD_level.log"""
        date_str = datetime.now().strftime("%Y%m%d")
        return self.log_dir / f"{date_str}_{self.level_name}.log"
    
    def doRollover(self):
        """
        执行日志文件轮转
        重写父类方法，使用自定义的文件命名规则
        """
        if self.stream:
            self.stream.close()
            self.stream = None
        
        # 更新到新的文件名
        self.baseFilename = str(self._generate_filename())
        
        # 打开新文件
        if not self.delay:
            self.stream = self._open()


def setup_logger(name="app", level=logging.DEBUG):
    """
    设置并返回一个配置好的logger实例
    
    Args:
        name: logger名称，默认"app"
        level: 日志级别，默认DEBUG
        
    Returns:
        logging.Logger: 配置好的logger实例
    """
    # 如果logger已存在，直接返回
    if name in _loggers:
        return _loggers[name]
    
    # 创建logger
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False  # 不传播到父logger
    
    # 清除已有的handlers（避免重复添加）
    logger.handlers.clear()
    
    # 创建格式化器
    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    
    # 控制台处理器（输出INFO及以上级别）
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # 为不同级别创建文件处理器
    levels = {
        'debug': logging.DEBUG,
        'info': logging.INFO,
        'error': logging.ERROR,
    }
    
    for level_name, level_value in levels.items():
        # 创建按天分割的文件处理器
        file_handler = DailyRotatingFileHandler(
            log_dir=LOG_DIR,
            level_name=level_name,
            when='midnight',
            interval=1,
            backup_count=30
        )
        file_handler.setLevel(level_value)
        file_handler.setFormatter(formatter)
        
        # 添加过滤器，只记录对应级别的日志
        if level_name == 'debug':
            # debug文件只记录DEBUG级别
            file_handler.addFilter(lambda record: record.levelno == logging.DEBUG)
        elif level_name == 'info':
            # info文件只记录INFO级别
            file_handler.addFilter(lambda record: record.levelno == logging.INFO)
        elif level_name == 'error':
            # error文件记录ERROR和CRITICAL级别
            file_handler.addFilter(lambda record: record.levelno >= logging.ERROR)
        
        logger.addHandler(file_handler)
    
    # 缓存logger
    _loggers[name] = logger
    
    return logger


# 创建默认logger实例
default_logger = setup_logger("app")

# 导出logger别名，方便导入使用
logger = default_logger


def get_logger(name="app"):
    """
    获取logger实例
    
    Args:
        name: logger名称，默认"app"
        
    Returns:
        logging.Logger: logger实例
    """
    if name in _loggers:
        return _loggers[name]
    return setup_logger(name)


# 提供便捷的日志函数
def debug(msg, *args, **kwargs):
    """记录DEBUG级别日志"""
    default_logger.debug(msg, *args, **kwargs)


def info(msg, *args, **kwargs):
    """记录INFO级别日志"""
    default_logger.info(msg, *args, **kwargs)

def error(msg, *args, **kwargs):
    """记录ERROR级别日志"""
    default_logger.error(msg, *args, **kwargs)


def critical(msg, *args, **kwargs):
    """记录CRITICAL级别日志"""
    default_logger.critical(msg, *args, **kwargs)


def exception(msg, *args, **kwargs):
    """记录异常信息（ERROR级别，包含堆栈跟踪）"""
    default_logger.exception(msg, *args, **kwargs)


# 使用示例
if __name__ == "__main__":
    # 测试日志功能
    logger = get_logger()
    
    logger.debug("这是一条DEBUG日志")
    logger.info("这是一条INFO日志")
    logger.error("这是一条ERROR日志")
    logger.critical("这是一条CRITICAL日志")
    
    try:
        1 / 0
    except Exception as e:
        logger.exception("捕获到异常")
    
    # 使用便捷函数
    debug("使用便捷函数记录DEBUG")
    info("使用便捷函数记录INFO")
    error("使用便捷函数记录ERROR")
