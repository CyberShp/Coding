#!/usr/bin/env python3
"""
主入口：python3 -m observation_gui
"""

import os
import sys
import logging
from pathlib import Path

# 抑制 macOS Tk 弃用警告
os.environ['TK_SILENCE_DEPRECATION'] = '1'


def setup_logging(level: str = "INFO"):
    """配置日志"""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )


def main():
    """主函数"""
    setup_logging()
    logger = logging.getLogger("observation_gui")
    
    logger.info("观察点监控平台启动...")
    
    # 检查 Tkinter 是否可用
    try:
        import tkinter as tk
    except ImportError:
        logger.error("Tkinter 不可用，请确保 Python 安装了 Tk 支持")
        sys.exit(1)
    
    # 加载配置
    config_path = Path(__file__).parent / "config.json"
    
    # 启动 GUI
    from .gui.main_window import MainWindow
    
    app = MainWindow(config_path)
    app.run()


if __name__ == "__main__":
    main()
