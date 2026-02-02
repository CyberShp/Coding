"""
工具函数

提供常用的辅助功能：命令执行、文件读取、解析等。
"""

import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 默认子进程超时时间（秒）
DEFAULT_TIMEOUT = 10


def run_command(
    cmd: str | list[str],
    timeout: int = DEFAULT_TIMEOUT,
    shell: bool = False,
    check: bool = False,
    capture_stderr: bool = True,
) -> tuple[int, str, str]:
    """
    执行命令并返回结果
    
    Args:
        cmd: 命令字符串或列表
        timeout: 超时时间（秒）
        shell: 是否使用 shell 执行
        check: 是否在非零返回码时抛出异常
        capture_stderr: 是否捕获 stderr
        
    Returns:
        (返回码, stdout, stderr)
    """
    try:
        if isinstance(cmd, str) and not shell:
            cmd = cmd.split()
        
        result = subprocess.run(
            cmd,
            shell=shell,
            timeout=timeout,
            capture_output=True,
            text=True,
            check=check,
        )
        
        return result.returncode, result.stdout, result.stderr
        
    except subprocess.TimeoutExpired:
        logger.warning(f"命令超时: {cmd}")
        return -1, "", "Timeout"
    except subprocess.CalledProcessError as e:
        return e.returncode, e.stdout or "", e.stderr or ""
    except Exception as e:
        logger.error(f"执行命令失败: {cmd}, 错误: {e}")
        return -1, "", str(e)


def read_sysfs(path: str | Path) -> str | None:
    """
    读取 sysfs 文件内容
    
    Args:
        path: sysfs 文件路径
        
    Returns:
        文件内容（去除首尾空白），或 None（如果读取失败）
    """
    try:
        path = Path(path)
        if not path.exists():
            return None
        return path.read_text().strip()
    except Exception as e:
        logger.debug(f"读取 sysfs 失败: {path}, 错误: {e}")
        return None


def tail_file(
    path: str | Path,
    last_position: int = 0,
    max_lines: int = 1000,
) -> tuple[list[str], int]:
    """
    读取文件新增内容（类似 tail -f）
    
    Args:
        path: 文件路径
        last_position: 上次读取的位置
        max_lines: 最大返回行数
        
    Returns:
        (新增行列表, 新的位置)
    """
    path = Path(path)
    
    if not path.exists():
        return [], 0
    
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            # 获取文件大小
            f.seek(0, 2)  # 移到文件末尾
            file_size = f.tell()
            
            # 如果文件变小了（可能被轮转），从头开始
            if file_size < last_position:
                last_position = 0
            
            # 移到上次位置
            f.seek(last_position)
            
            # 读取新内容
            lines = []
            for line in f:
                lines.append(line.rstrip('\n\r'))
                if len(lines) >= max_lines:
                    break
            
            new_position = f.tell()
            
            return lines, new_position
            
    except Exception as e:
        logger.error(f"读取文件失败: {path}, 错误: {e}")
        return [], last_position


def parse_key_value(text: str, sep: str = ':', strip: bool = True) -> dict[str, str]:
    """
    解析键值对格式的文本
    
    Args:
        text: 要解析的文本
        sep: 分隔符
        strip: 是否去除空白
        
    Returns:
        键值对字典
    """
    result = {}
    for line in text.split('\n'):
        if sep not in line:
            continue
        parts = line.split(sep, 1)
        if len(parts) == 2:
            key, value = parts
            if strip:
                key = key.strip()
                value = value.strip()
            result[key] = value
    return result


def safe_int(value: Any, default: int = 0) -> int:
    """
    安全转换为整数
    
    Args:
        value: 要转换的值
        default: 默认值
        
    Returns:
        整数值
    """
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    """
    安全转换为浮点数
    
    Args:
        value: 要转换的值
        default: 默认值
        
    Returns:
        浮点数值
    """
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def get_network_interfaces() -> list[str]:
    """
    获取网络接口列表
    
    Returns:
        接口名称列表
    """
    interfaces = []
    net_path = Path('/sys/class/net')
    
    if net_path.exists():
        for item in net_path.iterdir():
            if item.is_symlink() or item.is_dir():
                # 排除 lo
                if item.name != 'lo':
                    interfaces.append(item.name)
    
    return sorted(interfaces)


def get_pcie_devices() -> list[dict[str, str]]:
    """
    获取 PCIe 设备列表
    
    Returns:
        PCIe 设备信息列表
    """
    devices = []
    
    # 尝试使用 lspci
    ret, stdout, _ = run_command(['lspci', '-D'], timeout=5)
    if ret == 0:
        for line in stdout.split('\n'):
            if line.strip():
                parts = line.split(' ', 1)
                if len(parts) == 2:
                    devices.append({
                        'address': parts[0],
                        'description': parts[1],
                    })
    
    return devices
