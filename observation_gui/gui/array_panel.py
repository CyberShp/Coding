"""
阵列详情面板

显示单个阵列的监控状态和告警信息。
"""

import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, List, Optional

from ..core.array_manager import ArrayStatus, ConnectionState
from ..core.result_parser import ResultParser


class ArrayPanel(tk.Frame):
    """
    阵列详情面板
    
    显示：
    - 阵列基本信息
    - 连接状态
    - 各观察点状态
    - 最近告警列表
    """
    
    def __init__(self, parent, **kwargs):
        """
        初始化面板
        
        Args:
            parent: 父组件
        """
        super().__init__(parent, bg='#f5f5f5', **kwargs)
        
        self._build_ui()
    
    def _build_ui(self):
        """构建界面"""
        # 信息区
        info_frame = tk.LabelFrame(self, text="阵列信息", padx=10, pady=10, bg='#f5f5f5')
        info_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # 阵列名称和状态
        self.name_label = tk.Label(
            info_frame, 
            text="未选择阵列", 
            font=('', 14, 'bold'),
            bg='#f5f5f5',
        )
        self.name_label.pack(anchor=tk.W)
        
        self.status_label = tk.Label(info_frame, text="", bg='#f5f5f5')
        self.status_label.pack(anchor=tk.W, pady=(5, 0))
        
        self.host_label = tk.Label(info_frame, text="", bg='#f5f5f5')
        self.host_label.pack(anchor=tk.W)
        
        # 观察点状态区
        observer_frame = tk.LabelFrame(self, text="观察点状态", padx=10, pady=10, bg='#f5f5f5')
        observer_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 使用 Treeview 显示观察点状态
        columns = ('status', 'message')
        self.observer_tree = ttk.Treeview(
            observer_frame,
            columns=columns,
            show='tree headings',
            height=8,
        )
        
        self.observer_tree.heading('#0', text='观察点')
        self.observer_tree.heading('status', text='状态')
        self.observer_tree.heading('message', text='说明')
        
        self.observer_tree.column('#0', width=120)
        self.observer_tree.column('status', width=80)
        self.observer_tree.column('message', width=300)
        
        # 滚动条
        scrollbar = tk.Scrollbar(
            observer_frame, 
            orient=tk.VERTICAL,
            command=self.observer_tree.yview
        )
        self.observer_tree.configure(yscrollcommand=scrollbar.set)
        
        self.observer_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 最近告警区
        alert_frame = tk.LabelFrame(self, text="最近告警", padx=10, pady=10, bg='#f5f5f5')
        alert_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 告警列表
        alert_columns = ('time', 'level', 'observer', 'message')
        self.alert_tree = ttk.Treeview(
            alert_frame,
            columns=alert_columns,
            show='headings',
            height=6,
        )
        
        self.alert_tree.heading('time', text='时间')
        self.alert_tree.heading('level', text='级别')
        self.alert_tree.heading('observer', text='观察点')
        self.alert_tree.heading('message', text='消息')
        
        self.alert_tree.column('time', width=150)
        self.alert_tree.column('level', width=60)
        self.alert_tree.column('observer', width=100)
        self.alert_tree.column('message', width=350)
        
        alert_scrollbar = tk.Scrollbar(
            alert_frame,
            orient=tk.VERTICAL,
            command=self.alert_tree.yview
        )
        self.alert_tree.configure(yscrollcommand=alert_scrollbar.set)
        
        self.alert_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        alert_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 配置标签样式
        self._configure_tags()
    
    def _configure_tags(self):
        """配置 Treeview 标签样式"""
        # 观察点状态标签
        self.observer_tree.tag_configure('ok', foreground='#4CAF50')
        self.observer_tree.tag_configure('warning', foreground='#FF9800')
        self.observer_tree.tag_configure('error', foreground='#F44336')
        self.observer_tree.tag_configure('unknown', foreground='#9E9E9E')
        
        # 告警级别标签
        self.alert_tree.tag_configure('info', foreground='#2196F3')
        self.alert_tree.tag_configure('warning', foreground='#FF9800')
        self.alert_tree.tag_configure('error', foreground='#F44336')
        self.alert_tree.tag_configure('critical', foreground='#9C27B0')
    
    def clear(self):
        """清空面板"""
        self.name_label.config(text="未选择阵列")
        self.status_label.config(text="")
        self.host_label.config(text="")
        
        # 清空观察点列表
        for item in self.observer_tree.get_children():
            self.observer_tree.delete(item)
        
        # 清空告警列表
        for item in self.alert_tree.get_children():
            self.alert_tree.delete(item)
    
    def update_status(self, status: ArrayStatus):
        """
        更新阵列状态显示
        
        Args:
            status: 阵列状态
        """
        config = status.config
        
        # 更新基本信息
        self.name_label.config(text=config.name)
        self.host_label.config(text=f"地址: {config.host}:{config.port}")
        
        # 连接状态
        state_text = self._get_state_text(status)
        self.status_label.config(text=state_text)
        
        # 更新观察点状态
        self._update_observer_status(status.observer_status)
        
        # 更新告警列表
        self._update_alerts(status.recent_alerts)
    
    def _get_state_text(self, status: ArrayStatus) -> str:
        """获取状态文本"""
        state_map = {
            ConnectionState.DISCONNECTED: "状态: 未连接",
            ConnectionState.CONNECTING: "状态: 连接中...",
            ConnectionState.CONNECTED: "状态: 已连接",
            ConnectionState.ERROR: f"状态: 错误 - {status.last_error}",
        }
        
        text = state_map.get(status.state, "状态: 未知")
        
        if status.state == ConnectionState.CONNECTED:
            if status.agent_running:
                text += " | 监控运行中"
            elif status.agent_deployed:
                text += " | 监控未运行"
            else:
                text += " | Agent 未部署"
        
        if status.last_refresh:
            text += f" | 上次刷新: {status.last_refresh.strftime('%H:%M:%S')}"
        
        return text
    
    def _update_observer_status(self, observer_status: Dict[str, Dict[str, str]]):
        """更新观察点状态"""
        # 清空现有项
        for item in self.observer_tree.get_children():
            self.observer_tree.delete(item)
        
        if not observer_status:
            return
        
        # 格式化并添加
        formatted = ResultParser.format_observer_status(observer_status)
        
        for obs in formatted:
            status = obs['status']
            icon = obs['icon']
            
            self.observer_tree.insert(
                '',
                tk.END,
                text=obs['display_name'],
                values=(f"{icon} {status}", obs['message']),
                tags=(status,)
            )
    
    def _update_alerts(self, alerts: List[Dict[str, Any]]):
        """更新告警列表"""
        # 清空现有项
        for item in self.alert_tree.get_children():
            self.alert_tree.delete(item)
        
        if not alerts:
            return
        
        # 添加告警（最新的在前）
        for alert in reversed(alerts[-20:]):
            timestamp = alert.get('timestamp', '')
            if len(timestamp) > 19:
                timestamp = timestamp[:19]
            
            level = alert.get('level', 'info')
            observer = alert.get('observer_name', '')
            message = alert.get('message', '')
            
            # 截断过长的消息
            if len(message) > 100:
                message = message[:97] + '...'
            
            self.alert_tree.insert(
                '',
                0,  # 插入到开头
                values=(
                    timestamp,
                    level.upper(),
                    ResultParser.get_observer_display_name(observer),
                    message,
                ),
                tags=(level,)
            )
