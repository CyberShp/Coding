"""
工具函数

提供常用的辅助功能：命令执行、文件读取、解析等。
"""

import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

# 默认子进程超时时间（秒）
DEFAULT_TIMEOUT = 10


# PATH 初始化，用于 SSH/服务环境下 os_cli 等命令找不到时
_ENV_PATH_PREFIX = "export PATH=/usr/local/bin:/usr/bin:/bin:/sbin:/usr/sbin:$PATH && "


def run_command(
    cmd: Union[str, List[str]],
    timeout: int = DEFAULT_TIMEOUT,
    shell: bool = False,
    check: bool = False,
    capture_stderr: bool = True,
    ensure_path: bool = False,
):
    # type: (...) -> Tuple[int, str, str]
    """
    执行命令并返回结果

    Args:
        cmd: 命令字符串或列表
        timeout: 超时时间（秒）
        shell: 是否使用 shell 执行
        check: 是否在非零返回码时抛出异常
        capture_stderr: 是否捕获 stderr
        ensure_path: 若 True 且 shell=True，在命令前添加 PATH 初始化（解决 os_cli 等 cmd not found）
    Returns:
        (返回码, stdout, stderr)
    """
    try:
        if isinstance(cmd, str) and not shell:
            cmd = cmd.split()

        if ensure_path and shell and isinstance(cmd, str):
            cmd = _ENV_PATH_PREFIX + cmd

        run_kw = dict(shell=shell, timeout=timeout, check=check)
        if sys.version_info >= (3, 7):
            run_kw['capture_output'] = True
            run_kw['text'] = True
        else:
            run_kw['stdout'] = subprocess.PIPE
            run_kw['stderr'] = subprocess.PIPE
            run_kw['universal_newlines'] = True
        result = subprocess.run(cmd, **run_kw)
        
        return result.returncode, result.stdout, result.stderr
        
    except subprocess.TimeoutExpired:
        logger.warning(f"命令超时: {cmd}")
        return -1, "", "Timeout"
    except subprocess.CalledProcessError as e:
        return e.returncode, e.stdout or "", e.stderr or ""
    except Exception as e:
        logger.error(f"执行命令失败: {cmd}, 错误: {e}")
        return -1, "", str(e)


def read_sysfs(path: Union[str, Path]) -> Optional[str]:
    """
    读取 sysfs 文件内容

    端口 down 时 carrier 可能不存在或抛出 IOError(Invalid argument)，
    此时返回 None 由调用方处理。
    
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
    except (IOError, OSError) as e:
        # carrier 在端口 down 时可能抛出 Invalid argument
        logger.debug(f"读取 sysfs 失败 (端口可能 down): {path}, 错误: {e}")
        return None
    except Exception as e:
        logger.debug(f"读取 sysfs 失败: {path}, 错误: {e}")
        return None


def tail_file(
    path: Union[str, Path],
    last_position: int = 0,
    max_lines: int = 1000,
    skip_existing: bool = False,
):
    # type: (...) -> Tuple[List[str], int]
    """
    读取文件新增内容（类似 tail -f）
    
    Args:
        path: 文件路径
        last_position: 上次读取的位置
        max_lines: 最大返回行数
        skip_existing: 若为 True 且 last_position=0，则跳到文件末尾（用于启动时不读历史）
        
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
            
            # 如果 skip_existing=True 且首次运行，直接返回末尾位置
            if skip_existing and last_position == 0:
                return [], file_size
            
            # 如果文件变小了（可能被轮转），从头开始
            if file_size < last_position:
                last_position = 0
            
            # 移到上次位置
            f.seek(last_position)
            
            # 读取新内容（使用 readline 避免迭代器与 tell() 冲突）
            lines = []
            while True:
                line = f.readline()
                if not line:
                    break
                lines.append(line.rstrip('\n\r'))
                if len(lines) >= max_lines:
                    break
            
            new_position = f.tell()
            
            return lines, new_position
            
    except Exception as e:
        logger.error(f"读取文件失败: {path}, 错误: {e}")
        return [], last_position


def parse_key_value(text: str, sep: str = ':', strip: bool = True) -> Dict[str, str]:
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


def get_network_interfaces() -> List[str]:
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


def get_bus_to_slot_mapping(timeout: int = 15) -> Dict[str, str]:
    """
    执行 diagsh pciemgt showcarddevice 获取 bus 到 slot_id 的映射。

    命令输出为表格格式，(BS:SL.FN) 列为 bus 号，右侧为 SlotId 列。
    日志中的 bus 可能省略前导零（如 4.40.0），命令输出可能为 04.40.00，
    需做规范化匹配。

    Returns:
        {normalized_bus: slot_id} 例如 {"4.40.0": "3", "4.0": "1"}
    """
    mapping: Dict[str, str] = {}
    cmd = 'diagsh --attach="devm_21" --cmd="pciemgt showcarddevice"'
    ret, stdout, stderr = run_command(cmd, shell=True, timeout=timeout)
    if ret != 0:
        logger.debug("diagsh pciemgt showcarddevice 执行失败: %s", stderr[:200] if stderr else "unknown")
        return mapping

    def _normalize_bus(bus_str: str) -> str:
        """规范化 bus 字符串便于匹配：04.40.00 -> 4.40.0"""
        if not bus_str or not bus_str.strip():
            return ""
        parts = bus_str.strip().replace("(", "").replace(")", "").split(":")
        if len(parts) >= 2:
            bus_part = parts[-1].strip()  # 取冒号后的部分如 "04.40.00"
        else:
            bus_part = bus_str.strip()
        # 去掉前导零：04.40.00 -> 4.40.0
        segments = bus_part.split(".")
        normalized = ".".join(str(int(s)) if s.isdigit() else s for s in segments)
        return normalized

    lines = stdout.split("\n")
    # 查找表头行，定位 BS:SL.FN 和 SlotId 列
    bs_col = -1
    slot_col = -1
    header_found = False

    for i, line in enumerate(lines):
        # 表头可能包含 BS:SL.FN 或类似，以及 SlotId
        upper = line.upper()
        if "BS:SL.FN" in upper or "BS:SL" in upper:
            header_found = True
            cols = line.split()
            for j, c in enumerate(cols):
                if "BS" in c.upper() or "SL.FN" in c.upper():
                    bs_col = j
                if "SLOTID" in c.upper() or "SLOT" in c.upper():
                    slot_col = j
            if bs_col < 0:
                bs_col = 0
            if slot_col < 0:
                slot_col = bs_col + 1
            break

    if not header_found:
        # 尝试简单解析：每行包含 bus 和 slot，bus 格式为 xx.xx.xx
        for line in lines:
            line = line.strip()
            if not line or line.startswith("-") or line.startswith("="):
                continue
            # 匹配可能的 bus 格式：数字.数字.数字
            bus_match = re.search(r"(\d+\.\d+(?:\.\d+)?)", line)
            if bus_match:
                bus_raw = bus_match.group(1)
                parts = line.split()
                slot_id = ""
                for p in parts:
                    if p != bus_raw and p.replace(".", "").isdigit() is False and p.isalnum():
                        slot_id = p
                        break
                if not slot_id and len(parts) > 1:
                    idx = line.find(bus_raw)
                    rest = line[idx + len(bus_raw) :].strip().split()
                    slot_id = rest[0] if rest else ""
                if slot_id:
                    mapping[_normalize_bus(bus_raw)] = slot_id
        return mapping

    # 按表头解析数据行
    for line in lines[1:]:
        line = line.strip()
        if not line or line.startswith("-") or line.startswith("="):
            continue
        cols = line.split()
        if bs_col < len(cols) and slot_col < len(cols):
            bus_raw = cols[bs_col]
            slot_id = cols[slot_col]
            norm = _normalize_bus(bus_raw)
            if norm and slot_id:
                mapping[norm] = slot_id

    return mapping


def get_pcie_devices() -> List[Dict[str, str]]:
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
