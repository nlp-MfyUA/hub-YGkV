import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def safe_write(file_path: str, content: str) -> bool:
    """
    生产级安全写入函数。
    
    核心策略：先写临时文件，再原子性重命名，
    避免写入中断导致原文件被损坏。
    """
    path = Path(file_path)
    
    # 1. 确保目录存在
    path.parent.mkdir(parents=True, exist_ok=True)
    
    # 2. 先写入临时文件（.tmp 后缀）
    tmp_path = path.with_suffix(path.suffix + '.tmp')
    
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(content)
            f.flush()    # 强制刷新缓冲区到磁盘
            os.fsync(f.fileno())  # 强制操作系统刷盘，防止断电丢数据
        
        # 3. 原子性重命名（Linux 上 rename 是原子操作）
        tmp_path.rename(path)
        logger.info("文件写入成功: %s", file_path)
        return True
        
    except OSError as e:
        logger.error("文件写入失败: %s, 错误: %s", file_path, e)
        # 清理临时文件
        if tmp_path.exists():
            tmp_path.unlink()
        return False



def safe_append(file_path: str, content: str) -> bool:
    """
    生产级安全追加函数。
    不会直接打开原文件追加，而是读取、拼接、安全覆盖。
    """
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    # 注意：这里不能用 .tmp 后缀简单替换，因为如果原文件没有后缀会出问题
    # 使用同目录下的隐藏临时文件更安全
    tmp_path = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    
    try:
        # 1. 读取原文件内容（如果存在）
        original_content = ""
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                original_content = f.read()
                
        # 2. 在内存中拼接
        new_content = original_content + content
        
        # 3. 将拼接后的完整内容写入临时文件
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
            f.flush()
            os.fsync(f.fileno())
            
        # 4. 原子替换
        # 【改进点】推荐使用 os.replace 而不是 Path.rename
        # os.replace 在 Windows 和 Linux 上都是真正的原子操作，且能覆盖已存在的文件
        os.replace(tmp_path, path)
        
        logger.info("文件安全追加成功: %s", file_path)
        return True
        
    except OSError as e:
        logger.error("文件追加失败: %s, 错误: %s", file_path, e)
        if tmp_path.exists():
            tmp_path.unlink()
        return False


