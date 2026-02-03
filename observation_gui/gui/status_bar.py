"""
状态栏

显示全局状态信息：连接数、刷新时间等。
"""

import tkinter as tk
from tkinter import ttk
from datetime import datetime


class StatusBar(tk.Frame):
    """
    状态栏
    
    显示：
    - 连接状态统计
    - 刷新间隔
    - 上次刷新时间
    - 临时消息
    """
    
    def __init__(self, parent, **kwargs):
        """
        初始化状态栏
        
        Args:
            parent: 父组件
        """
        super().__init__(parent, bg='#e0e0e0', **kwargs)
        
        self._build_ui()
    
    def _build_ui(self):
        """构建界面"""
        # 分隔线
        separator = tk.Frame(self, height=1, bg='#999999')
        separator.pack(fill=tk.X)
        
        # 状态栏内容
        content_frame = tk.Frame(self, bg='#e0e0e0')
        content_frame.pack(fill=tk.X, padx=5, pady=3)
        
        # 左侧：消息
        self.message_label = tk.Label(content_frame, text="就绪", bg='#e0e0e0')
        self.message_label.pack(side=tk.LEFT)
        
        # 右侧：状态信息
        right_frame = tk.Frame(content_frame, bg='#e0e0e0')
        right_frame.pack(side=tk.RIGHT)
        
        # 连接状态
        self.connection_label = tk.Label(right_frame, text="已连接: 0/0", bg='#e0e0e0')
        self.connection_label.pack(side=tk.LEFT, padx=(0, 15))
        
        # 运行状态
        self.running_label = tk.Label(right_frame, text="运行中: 0", bg='#e0e0e0')
        self.running_label.pack(side=tk.LEFT, padx=(0, 15))
        
        # 刷新时间
        self.refresh_label = tk.Label(right_frame, text="刷新间隔: 30s", bg='#e0e0e0')
        self.refresh_label.pack(side=tk.LEFT, padx=(0, 15))
        
        # 上次刷新
        self.last_refresh_label = tk.Label(right_frame, text="", bg='#e0e0e0')
        self.last_refresh_label.pack(side=tk.LEFT)
    
    def update_status(
        self,
        connected: int = 0,
        total: int = 0,
        running: int = 0,
        refresh_interval: int = 30,
    ):
        """
        更新状态显示
        
        Args:
            connected: 已连接阵列数
            total: 总阵列数
            running: 运行监控的阵列数
            refresh_interval: 刷新间隔（秒）
        """
        self.connection_label.config(text=f"已连接: {connected}/{total}")
        self.running_label.config(text=f"运行中: {running}")
        self.refresh_label.config(text=f"刷新间隔: {refresh_interval}s")
        self.last_refresh_label.config(
            text=f"上次刷新: {datetime.now().strftime('%H:%M:%S')}"
        )
    
    def set_message(self, message: str, duration: int = 3000):
        """
        设置临时消息
        
        Args:
            message: 消息内容
            duration: 显示时长（毫秒），0 表示永久
        """
        self.message_label.config(text=message)
        
        if duration > 0:
            self.after(duration, self._clear_message)
    
    def _clear_message(self):
        """清除临时消息"""
        self.message_label.config(text="就绪")
