#!/usr/bin/env python3
"""
主入口：python3 -m observation_points
"""

import argparse
import fcntl
import logging
from logging.handlers import RotatingFileHandler
import os
import signal
import sys
from pathlib import Path
from typing import Optional

from .config.loader import ConfigLoader
from .core.scheduler import Scheduler
from .core.reporter import Reporter
from .utils.helpers import configure_default_timeout


def setup_logging(log_level: str, log_file: Optional[str] = None):
    """配置日志系统"""
    level = getattr(logging, log_level.upper(), logging.INFO)
    
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(RotatingFileHandler(
            log_file,
            maxBytes=20 * 1024 * 1024,
            backupCount=3,
            encoding='utf-8',
        ))
    
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=handlers
    )


def main():
    parser = argparse.ArgumentParser(
        description='观察点监控系统 - 存储阵列全局观察点监控'
    )
    parser.add_argument(
        '-c', '--config',
        default='/etc/observation-points/config.json',
        help='配置文件路径 (默认: /etc/observation-points/config.json，仅支持 JSON)'
    )
    parser.add_argument(
        '--log-level',
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        help='日志级别 (默认: INFO)'
    )
    parser.add_argument(
        '--log-file',
        help='日志文件路径 (可选)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='试运行模式，不实际执行告警'
    )
    parser.add_argument(
        '--alert-level',
        default='INFO',
        choices=['INFO', 'WARNING', 'ERROR'],
        help='最低告警级别筛选（默认 INFO 显示所有）'
    )
    
    args = parser.parse_args()
    
    # 设置日志
    setup_logging(args.log_level, args.log_file)
    logger = logging.getLogger('observation_points')
    
    # 加载配置
    config_path = Path(args.config)
    if not config_path.exists():
        # 尝试使用项目目录下的默认配置
        default_config = Path(__file__).parent / 'config.json'
        if default_config.exists():
            config_path = default_config
            logger.info(f"使用默认配置文件: {config_path}")
        else:
            logger.error(f"配置文件不存在: {args.config}")
            sys.exit(1)
    
    try:
        config = ConfigLoader.load(config_path)
    except Exception as e:
        logger.error(f"加载配置失败: {e}")
        sys.exit(1)

    lock_path = Path((config.get('global', {}) or {}).get(
        'lock_path', '/var/run/observation-points.lock'
    ))
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_handle = open(lock_path, 'a+')
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        logger.error("已有 Agent 实例正在运行: %s", lock_path)
        sys.exit(1)

    # Runtime restart context for updater (preserve current launch arguments).
    package_name = (__package__ or 'observation_points').split('.')[0]
    restart_argv = ['-m', package_name] + sys.argv[1:]
    config['_runtime'] = {
        'python_executable': sys.executable,
        'argv': restart_argv,
    }
    configure_default_timeout((config.get('global', {}) or {}).get('subprocess_timeout', 10))
    
    logger.info(f"观察点监控系统启动，版本: 1.0.0")
    logger.info(f"配置文件: {config_path}")
    
    # 创建告警器
    reporter = Reporter(
        config.get('reporter', {}),
        dry_run=args.dry_run,
        min_level=args.alert_level
    )
    
    # 创建调度器并注册观察点
    scheduler = Scheduler(config, reporter)
    
    # 信号处理
    reload_requested = [False]

    def signal_handler(signum, frame):
        logger.info("收到退出信号，正在停止...")
        if signum == getattr(signal, 'SIGHUP', None):
            reload_requested[0] = True
        scheduler.stop()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    if hasattr(signal, 'SIGHUP'):
        signal.signal(signal.SIGHUP, signal_handler)
    
    # 启动调度器
    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("用户中断，正在停止...")
        scheduler.stop()
    except Exception as e:
        logger.error(f"运行时错误: {e}")
        scheduler.stop()
        raise
    finally:
        reporter.close(drain_timeout=5)

    if reload_requested[0]:
        logger.info("重新加载配置并重启 Agent 进程")
        os.execv(sys.executable, [sys.executable] + restart_argv)


if __name__ == '__main__':
    main()
