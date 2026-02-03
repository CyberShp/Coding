"""
主窗口

Tkinter 主界面，包含菜单、阵列列表、详情面板、状态栏。
"""

import json
import logging
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from typing import Any, Dict, Optional

from ..core.array_manager import ArrayManager, ArrayConfig, ConnectionState
from ..core.result_parser import ResultParser
from .login_dialog import LoginDialog
from .array_panel import ArrayPanel
from .status_bar import StatusBar

logger = logging.getLogger(__name__)


class MainWindow:
    """
    主窗口
    
    布局：
    ┌─────────────────────────────────────────────┐
    │  菜单栏                                      │
    ├─────────────────────────────────────────────┤
    │ ┌─────────┐ ┌─────────────────────────────┐ │
    │ │ 阵列列表 │ │       详情面板              │ │
    │ │         │ │                             │ │
    │ └─────────┘ └─────────────────────────────┘ │
    ├─────────────────────────────────────────────┤
    │  状态栏                                      │
    └─────────────────────────────────────────────┘
    """
    
    def __init__(self, config_path: Optional[Path] = None):
        """
        初始化主窗口
        
        Args:
            config_path: 配置文件路径
        """
        self.config_path = config_path or Path(__file__).parent.parent / "config.json"
        self.config = self._load_config()
        
        # 创建主窗口
        self.root = tk.Tk()
        self.root.title(self.config.get('app', {}).get('title', '观察点监控平台'))
        
        width = self.config.get('app', {}).get('window_width', 1000)
        height = self.config.get('app', {}).get('window_height', 700)
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(800, 600)
        
        # 阵列管理器
        self.array_manager = ArrayManager(self.config_path)
        self.array_manager.add_callback(self._on_array_event)
        
        # 当前选中的阵列 ID
        self._selected_array_id = None
        
        # 刷新定时器
        self._refresh_interval = self.config.get('app', {}).get('refresh_interval', 30)
        self._refresh_job = None
        
        # 构建界面
        self._build_ui()
        
        # 绑定事件
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        
        # 初始刷新
        self._refresh_array_list()
    
    def _load_config(self) -> Dict[str, Any]:
        """加载配置"""
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"加载配置失败: {e}")
        
        return {
            'app': {
                'title': '观察点监控平台',
                'refresh_interval': 30,
                'window_width': 1000,
                'window_height': 700,
            }
        }
    
    def _build_ui(self):
        """构建界面"""
        # 菜单栏
        self._build_menu()
        
        # 主框架
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 使用 PanedWindow 实现可调整大小的分割
        paned = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)
        
        # 左侧：阵列列表
        left_frame = self._build_array_list(paned)
        paned.add(left_frame, weight=1)
        
        # 右侧：详情面板
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=4)
        
        self.array_panel = ArrayPanel(right_frame)
        self.array_panel.pack(fill=tk.BOTH, expand=True)
        
        # 状态栏
        self.status_bar = StatusBar(self.root)
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)
    
    def _build_menu(self):
        """构建菜单栏"""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        # 文件菜单
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="文件(F)", menu=file_menu)
        file_menu.add_command(label="刷新", command=self._manual_refresh, accelerator="F5")
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self._on_close)
        
        # 阵列菜单
        array_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="阵列(A)", menu=array_menu)
        array_menu.add_command(label="添加阵列...", command=self._add_array)
        array_menu.add_command(label="移除阵列", command=self._remove_array)
        array_menu.add_separator()
        array_menu.add_command(label="连接", command=self._connect_selected)
        array_menu.add_command(label="断开", command=self._disconnect_selected)
        array_menu.add_separator()
        array_menu.add_command(label="启动监控", command=self._start_monitoring)
        array_menu.add_command(label="停止监控", command=self._stop_monitoring)
        
        # 帮助菜单
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="帮助(H)", menu=help_menu)
        help_menu.add_command(label="关于", command=self._show_about)
        
        # 快捷键
        self.root.bind('<F5>', lambda e: self._manual_refresh())
    
    def _build_array_list(self, parent) -> ttk.Frame:
        """构建阵列列表"""
        frame = ttk.Frame(parent, width=200)
        
        # 标题
        title_label = ttk.Label(frame, text="阵列列表", font=('', 12, 'bold'))
        title_label.pack(pady=(5, 10))
        
        # 列表框
        list_frame = ttk.Frame(frame)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5)
        
        self.array_listbox = tk.Listbox(
            list_frame,
            selectmode=tk.SINGLE,
            font=('', 10),
            activestyle='none',
        )
        self.array_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.array_listbox.config(yscrollcommand=scrollbar.set)
        scrollbar.config(command=self.array_listbox.yview)
        
        self.array_listbox.bind('<<ListboxSelect>>', self._on_array_select)
        self.array_listbox.bind('<Double-1>', self._on_array_double_click)
        
        # 按钮
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, padx=5, pady=10)
        
        add_btn = ttk.Button(btn_frame, text="+ 添加", command=self._add_array)
        add_btn.pack(side=tk.LEFT, padx=2)
        
        connect_btn = ttk.Button(btn_frame, text="连接", command=self._connect_selected)
        connect_btn.pack(side=tk.LEFT, padx=2)
        
        return frame
    
    def _refresh_array_list(self):
        """刷新阵列列表"""
        self.array_listbox.delete(0, tk.END)
        
        for status in self.array_manager.get_all_arrays():
            # 状态图标
            if status.state == ConnectionState.CONNECTED:
                if status.agent_running:
                    icon = "● "  # 运行中
                else:
                    icon = "○ "  # 已连接但未运行
            elif status.state == ConnectionState.CONNECTING:
                icon = "◐ "  # 连接中
            elif status.state == ConnectionState.ERROR:
                icon = "✗ "  # 错误
            else:
                icon = "○ "  # 未连接
            
            display = f"{icon}{status.config.name}"
            self.array_listbox.insert(tk.END, display)
            
            # 存储 ID 用于查找
            self.array_listbox.itemconfig(
                tk.END,
                selectbackground='#0078D7',
                selectforeground='white',
            )
    
    def _on_array_select(self, event):
        """阵列选择事件"""
        selection = self.array_listbox.curselection()
        if not selection:
            return
        
        index = selection[0]
        arrays = self.array_manager.get_all_arrays()
        
        if index < len(arrays):
            self._selected_array_id = arrays[index].config.id
            self._update_detail_panel()
    
    def _on_array_double_click(self, event):
        """阵列双击事件（连接/断开）"""
        if self._selected_array_id:
            status = self.array_manager.get_array(self._selected_array_id)
            if status and status.state == ConnectionState.CONNECTED:
                self._disconnect_selected()
            else:
                self._connect_selected()
    
    def _update_detail_panel(self):
        """更新详情面板"""
        if not self._selected_array_id:
            self.array_panel.clear()
            return
        
        status = self.array_manager.get_array(self._selected_array_id)
        if status:
            self.array_panel.update_status(status)
    
    def _on_array_event(self, event: str, array_id: str):
        """阵列事件回调"""
        # 在主线程中更新 UI
        self.root.after(0, self._handle_array_event, event, array_id)
    
    def _handle_array_event(self, event: str, array_id: str):
        """处理阵列事件"""
        self._refresh_array_list()
        
        if array_id == self._selected_array_id:
            self._update_detail_panel()
        
        # 更新状态栏
        summary = self.array_manager.get_summary()
        self.status_bar.update_status(
            connected=summary['connected_arrays'],
            total=summary['total_arrays'],
            running=summary['running_arrays'],
        )
    
    def _add_array(self):
        """添加阵列"""
        dialog = LoginDialog(self.root)
        result = dialog.show()
        
        if result:
            config = ArrayConfig(
                id=f"array_{len(self.array_manager.get_all_arrays()) + 1}",
                name=result['name'],
                host=result['host'],
                port=result.get('port', 22),
                username=result['username'],
                password=result.get('password', ''),
                key_path=result.get('key_path', ''),
            )
            
            if self.array_manager.add_array(config):
                self._refresh_array_list()
                
                # 自动连接
                if messagebox.askyesno("连接", "是否立即连接到此阵列？"):
                    self._connect_array_async(config.id)
    
    def _remove_array(self):
        """移除阵列"""
        if not self._selected_array_id:
            messagebox.showwarning("提示", "请先选择一个阵列")
            return
        
        status = self.array_manager.get_array(self._selected_array_id)
        if status and messagebox.askyesno(
            "确认",
            f"确定要移除阵列 '{status.config.name}' 吗？"
        ):
            self.array_manager.remove_array(self._selected_array_id)
            self._selected_array_id = None
            self._refresh_array_list()
            self.array_panel.clear()
    
    def _connect_selected(self):
        """连接选中的阵列"""
        if not self._selected_array_id:
            messagebox.showwarning("提示", "请先选择一个阵列")
            return
        
        status = self.array_manager.get_array(self._selected_array_id)
        if status and status.state == ConnectionState.CONNECTED:
            messagebox.showinfo("提示", "阵列已连接")
            return
        
        # 如果没有密码，弹出输入框
        if status and not status.config.password and not status.config.key_path:
            from tkinter import simpledialog
            password = simpledialog.askstring(
                "密码",
                f"请输入 {status.config.username}@{status.config.host} 的密码：",
                show='*',
                parent=self.root,
            )
            if password:
                status.config.password = password
            else:
                return
        
        self._connect_array_async(self._selected_array_id)
    
    def _connect_array_async(self, array_id: str):
        """异步连接阵列"""
        def do_connect():
            result = self.array_manager.connect_array(array_id)
            if not result:
                self.root.after(0, lambda: messagebox.showerror(
                    "连接失败",
                    f"无法连接到阵列，请检查网络和认证信息"
                ))
        
        self.status_bar.set_message("正在连接...")
        threading.Thread(target=do_connect, daemon=True).start()
    
    def _disconnect_selected(self):
        """断开选中的阵列"""
        if self._selected_array_id:
            self.array_manager.disconnect_array(self._selected_array_id)
            self._refresh_array_list()
            self._update_detail_panel()
    
    def _start_monitoring(self):
        """启动监控"""
        if not self._selected_array_id:
            messagebox.showwarning("提示", "请先选择一个阵列")
            return
        
        status = self.array_manager.get_array(self._selected_array_id)
        if not status or status.state != ConnectionState.CONNECTED:
            messagebox.showwarning("提示", "请先连接阵列")
            return
        
        def do_start():
            result = self.array_manager.start_monitoring(self._selected_array_id)
            if result:
                self.root.after(0, lambda: messagebox.showinfo("成功", "监控已启动"))
            else:
                self.root.after(0, lambda: messagebox.showerror("失败", "启动监控失败"))
        
        self.status_bar.set_message("正在启动监控...")
        threading.Thread(target=do_start, daemon=True).start()
    
    def _stop_monitoring(self):
        """停止监控"""
        if not self._selected_array_id:
            messagebox.showwarning("提示", "请先选择一个阵列")
            return
        
        def do_stop():
            result = self.array_manager.stop_monitoring(self._selected_array_id)
            self.root.after(0, self._refresh_array_list)
        
        threading.Thread(target=do_stop, daemon=True).start()
    
    def _manual_refresh(self):
        """手动刷新"""
        def do_refresh():
            self.array_manager.refresh_all()
            self.root.after(0, self._update_after_refresh)
        
        self.status_bar.set_message("正在刷新...")
        threading.Thread(target=do_refresh, daemon=True).start()
    
    def _update_after_refresh(self):
        """刷新后更新界面"""
        self._refresh_array_list()
        self._update_detail_panel()
        
        summary = self.array_manager.get_summary()
        self.status_bar.update_status(
            connected=summary['connected_arrays'],
            total=summary['total_arrays'],
            running=summary['running_arrays'],
        )
        self.status_bar.set_message("刷新完成")
    
    def _schedule_refresh(self):
        """调度定时刷新"""
        if self._refresh_job:
            self.root.after_cancel(self._refresh_job)
        
        self._refresh_job = self.root.after(
            self._refresh_interval * 1000,
            self._auto_refresh
        )
    
    def _auto_refresh(self):
        """自动刷新"""
        def do_refresh():
            self.array_manager.refresh_all()
            self.root.after(0, self._update_after_refresh)
            self.root.after(0, self._schedule_refresh)
        
        threading.Thread(target=do_refresh, daemon=True).start()
    
    def _show_about(self):
        """显示关于对话框"""
        messagebox.showinfo(
            "关于",
            "观察点监控平台 v1.0.0\n\n"
            "基于 Tkinter 的多阵列可视化监控工具\n"
            "通过 SSH 连接远程阵列执行监控任务"
        )
    
    def _on_close(self):
        """关闭窗口"""
        # 断开所有连接
        for status in self.array_manager.get_all_arrays():
            self.array_manager.disconnect_array(status.config.id)
        
        self.root.destroy()
    
    def run(self):
        """运行主循环"""
        # 启动定时刷新
        self._schedule_refresh()
        
        # 进入主循环
        self.root.mainloop()
