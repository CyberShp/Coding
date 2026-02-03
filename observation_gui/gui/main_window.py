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
        
        # 当前选中的阵列 ID 和文件夹
        self._selected_array_id = None
        self._selected_folder = None
        
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
        
        # 状态栏（先创建，放在底部）
        self.status_bar = StatusBar(self.root)
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        
        # 主框架
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 使用 tk.PanedWindow（macOS 兼容性更好）
        paned = tk.PanedWindow(main_frame, orient=tk.HORIZONTAL, sashrelief=tk.RAISED)
        paned.pack(fill=tk.BOTH, expand=True)
        
        # 左侧：阵列列表
        left_frame = self._build_array_list(paned)
        paned.add(left_frame, minsize=150, width=200)
        
        # 右侧：详情面板
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, minsize=400)
        
        self.array_panel = ArrayPanel(right_frame)
        self.array_panel.pack(fill=tk.BOTH, expand=True)
        
        # 强制刷新布局
        self.root.update_idletasks()
    
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
    
    def _build_array_list(self, parent) -> tk.Frame:
        """构建阵列列表（使用 Treeview 实现文件夹树）"""
        # 使用 tk.Frame 替代 ttk.Frame，macOS 兼容性更好
        frame = tk.Frame(parent, width=220, bg='#f0f0f0')
        
        # 标题
        title_label = tk.Label(
            frame, text="阵列列表", 
            font=('', 12, 'bold'),
            bg='#f0f0f0'
        )
        title_label.pack(pady=(10, 5))
        
        # 树形列表框
        tree_frame = tk.Frame(frame, bg='#f0f0f0')
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=5)
        
        # 使用 Treeview 实现文件夹树
        self.array_tree = ttk.Treeview(
            tree_frame,
            selectmode='browse',
            show='tree',  # 只显示树，不显示列头
        )
        self.array_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.array_tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.array_tree.configure(yscrollcommand=scrollbar.set)
        
        # 绑定事件
        self.array_tree.bind('<<TreeviewSelect>>', self._on_tree_select)
        self.array_tree.bind('<Double-1>', self._on_tree_double_click)
        self.array_tree.bind('<Button-3>', self._on_tree_right_click)  # 右键菜单
        
        # 拖拽支持
        self.array_tree.bind('<ButtonPress-1>', self._on_drag_start)
        self.array_tree.bind('<B1-Motion>', self._on_drag_motion)
        self.array_tree.bind('<ButtonRelease-1>', self._on_drag_release)
        self._drag_data = {'item': None, 'x': 0, 'y': 0}
        
        # 按钮区域
        btn_frame = tk.Frame(frame, bg='#f0f0f0')
        btn_frame.pack(fill=tk.X, padx=5, pady=5)
        
        add_folder_btn = tk.Button(
            btn_frame, text="+文件夹", 
            command=self._add_folder,
            relief=tk.RAISED,
            font=('', 9),
        )
        add_folder_btn.pack(side=tk.LEFT, padx=2)
        
        add_btn = tk.Button(
            btn_frame, text="+阵列", 
            command=self._add_array,
            relief=tk.RAISED,
            font=('', 9),
        )
        add_btn.pack(side=tk.LEFT, padx=2)
        
        # 第二行按钮
        btn_frame2 = tk.Frame(frame, bg='#f0f0f0')
        btn_frame2.pack(fill=tk.X, padx=5, pady=(0, 10))
        
        connect_btn = tk.Button(
            btn_frame2, text="连接", 
            command=self._connect_selected,
            relief=tk.RAISED,
            font=('', 9),
        )
        connect_btn.pack(side=tk.LEFT, padx=2)
        
        disconnect_btn = tk.Button(
            btn_frame2, text="断开",
            command=self._disconnect_selected,
            relief=tk.RAISED,
            font=('', 9),
        )
        disconnect_btn.pack(side=tk.LEFT, padx=2)
        
        # 创建右键菜单
        self._create_context_menus()
        
        return frame
    
    def _create_context_menus(self):
        """创建右键菜单"""
        # 文件夹右键菜单
        self.folder_menu = tk.Menu(self.root, tearoff=0)
        self.folder_menu.add_command(label="重命名", command=self._rename_folder)
        self.folder_menu.add_command(label="删除文件夹", command=self._delete_folder)
        
        # 阵列右键菜单
        self.array_menu = tk.Menu(self.root, tearoff=0)
        self.array_menu.add_command(label="连接", command=self._connect_selected)
        self.array_menu.add_command(label="断开", command=self._disconnect_selected)
        self.array_menu.add_separator()
        self.array_menu.add_command(label="移动到...", command=self._show_move_menu)
        self.array_menu.add_separator()
        self.array_menu.add_command(label="删除", command=self._remove_array)
    
    def _refresh_array_list(self):
        """刷新阵列列表（文件夹树结构）"""
        # 保存当前选中项和展开状态
        selected = self.array_tree.selection()
        expanded_folders = set()
        for item in self.array_tree.get_children(''):
            if self.array_tree.item(item, 'open'):
                expanded_folders.add(self.array_tree.item(item, 'text'))
        
        # 清空树
        for item in self.array_tree.get_children(''):
            self.array_tree.delete(item)
        
        # 获取按文件夹分组的阵列
        grouped = self.array_manager.get_arrays_grouped_by_folder()
        folders = self.array_manager.get_folders()
        
        # 添加文件夹和阵列
        for folder in folders:
            folder_id = f"folder_{folder}"
            # 文件夹图标
            self.array_tree.insert(
                '', 'end', 
                iid=folder_id,
                text=f"📁 {folder}",
                open=folder in expanded_folders,
                tags=('folder',)
            )
            
            # 添加该文件夹下的阵列
            for status in grouped.get(folder, []):
                self._insert_array_item(folder_id, status)
        
        # 未分类（空文件夹名）
        uncategorized = grouped.get("", [])
        if uncategorized or not folders:
            folder_id = "folder_uncategorized"
            self.array_tree.insert(
                '', 'end',
                iid=folder_id,
                text="📁 未分类",
                open="未分类" in expanded_folders or not folders,
                tags=('folder',)
            )
            for status in uncategorized:
                self._insert_array_item(folder_id, status)
        
        # 恢复选中项
        if selected:
            try:
                self.array_tree.selection_set(selected)
            except tk.TclError:
                pass
    
    def _insert_array_item(self, parent: str, status):
        """插入阵列项到树中"""
        # 状态图标
        if status.state == ConnectionState.CONNECTED:
            if status.agent_running:
                icon = "●"  # 运行中
            else:
                icon = "○"  # 已连接但未运行
        elif status.state == ConnectionState.CONNECTING:
            icon = "◐"  # 连接中
        elif status.state == ConnectionState.ERROR:
            icon = "✗"  # 错误
        else:
            icon = "○"  # 未连接
        
        display = f"{icon} {status.config.name}"
        self.array_tree.insert(
            parent, 'end',
            iid=f"array_{status.config.id}",
            text=display,
            tags=('array',)
        )
    
    def _get_status_icon(self, status) -> str:
        """获取状态图标"""
        if status.state == ConnectionState.CONNECTED:
            return "●" if status.agent_running else "○"
        elif status.state == ConnectionState.CONNECTING:
            return "◐"
        elif status.state == ConnectionState.ERROR:
            return "✗"
        return "○"
    
    def _on_tree_select(self, event):
        """树选择事件"""
        selection = self.array_tree.selection()
        if not selection:
            self._selected_array_id = None
            return
        
        item_id = selection[0]
        
        # 检查是否是阵列项
        if item_id.startswith('array_'):
            array_id = item_id[6:]  # 去掉 'array_' 前缀
            self._selected_array_id = array_id
            self._update_detail_panel()
        else:
            # 选中的是文件夹
            self._selected_array_id = None
            self.array_panel.clear()
    
    def _on_tree_double_click(self, event):
        """树双击事件"""
        item_id = self.array_tree.identify_row(event.y)
        if not item_id:
            return
        
        if item_id.startswith('array_'):
            # 双击阵列：连接/断开
            array_id = item_id[6:]
            status = self.array_manager.get_array(array_id)
            if status and status.state == ConnectionState.CONNECTED:
                self._disconnect_selected()
            else:
                self._selected_array_id = array_id
                self._connect_selected()
        else:
            # 双击文件夹：展开/折叠
            is_open = self.array_tree.item(item_id, 'open')
            self.array_tree.item(item_id, open=not is_open)
    
    def _on_tree_right_click(self, event):
        """树右键点击事件"""
        item_id = self.array_tree.identify_row(event.y)
        if not item_id:
            return
        
        # 选中该项
        self.array_tree.selection_set(item_id)
        
        if item_id.startswith('array_'):
            # 阵列右键菜单
            self._selected_array_id = item_id[6:]
            self.array_menu.tk_popup(event.x_root, event.y_root)
        elif item_id.startswith('folder_'):
            # 文件夹右键菜单
            folder_name = self.array_tree.item(item_id, 'text').replace('📁 ', '')
            self._selected_folder = folder_name
            if folder_name != "未分类":
                self.folder_menu.tk_popup(event.x_root, event.y_root)
    
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
    
    # ==================== 拖拽支持 ====================
    
    def _on_drag_start(self, event):
        """开始拖拽"""
        item_id = self.array_tree.identify_row(event.y)
        if item_id and item_id.startswith('array_'):
            self._drag_data['item'] = item_id
            self._drag_data['x'] = event.x
            self._drag_data['y'] = event.y
        else:
            self._drag_data['item'] = None
    
    def _on_drag_motion(self, event):
        """拖拽移动"""
        if self._drag_data['item']:
            # 可以添加视觉反馈，例如高亮目标文件夹
            pass
    
    def _on_drag_release(self, event):
        """释放拖拽"""
        if not self._drag_data['item']:
            return
        
        # 获取释放位置的项
        target_id = self.array_tree.identify_row(event.y)
        source_id = self._drag_data['item']
        
        if not target_id or source_id == target_id:
            self._drag_data['item'] = None
            return
        
        # 获取源阵列 ID
        array_id = source_id[6:]  # 去掉 'array_' 前缀
        
        # 确定目标文件夹
        if target_id.startswith('folder_'):
            # 拖到文件夹上
            if target_id == 'folder_uncategorized':
                target_folder = ""
            else:
                target_folder = target_id[7:]  # 去掉 'folder_' 前缀
        elif target_id.startswith('array_'):
            # 拖到另一个阵列上，获取其所属文件夹
            parent = self.array_tree.parent(target_id)
            if parent == 'folder_uncategorized':
                target_folder = ""
            else:
                target_folder = parent[7:] if parent.startswith('folder_') else ""
        else:
            self._drag_data['item'] = None
            return
        
        # 移动阵列到文件夹
        if self.array_manager.move_array_to_folder(array_id, target_folder):
            self._refresh_array_list()
        
        self._drag_data['item'] = None
    
    # ==================== 文件夹操作 ====================
    
    def _add_folder(self):
        """添加文件夹"""
        from tkinter import simpledialog
        name = simpledialog.askstring(
            "新建文件夹",
            "请输入文件夹名称：",
            parent=self.root,
        )
        if name and name.strip():
            if self.array_manager.add_folder(name.strip()):
                self._refresh_array_list()
            else:
                messagebox.showwarning("提示", "文件夹已存在或名称无效")
    
    def _rename_folder(self):
        """重命名文件夹"""
        if not hasattr(self, '_selected_folder'):
            return
        
        from tkinter import simpledialog
        new_name = simpledialog.askstring(
            "重命名文件夹",
            f"请输入新名称（当前：{self._selected_folder}）：",
            parent=self.root,
            initialvalue=self._selected_folder,
        )
        if new_name and new_name.strip() and new_name != self._selected_folder:
            if self.array_manager.rename_folder(self._selected_folder, new_name.strip()):
                self._refresh_array_list()
            else:
                messagebox.showwarning("提示", "重命名失败，新名称可能已存在")
    
    def _delete_folder(self):
        """删除文件夹"""
        if not hasattr(self, '_selected_folder'):
            return
        
        if messagebox.askyesno(
            "确认删除",
            f"确定要删除文件夹 '{self._selected_folder}' 吗？\n（文件夹内的阵列将移动到未分类）"
        ):
            if self.array_manager.remove_folder(self._selected_folder):
                self._refresh_array_list()
    
    def _show_move_menu(self):
        """显示移动到文件夹的菜单"""
        if not self._selected_array_id:
            return
        
        # 创建移动菜单
        move_menu = tk.Menu(self.root, tearoff=0)
        
        # 添加所有文件夹选项
        folders = self.array_manager.get_folders()
        for folder in folders:
            move_menu.add_command(
                label=folder,
                command=lambda f=folder: self._move_to_folder(f)
            )
        
        if folders:
            move_menu.add_separator()
        
        move_menu.add_command(
            label="未分类",
            command=lambda: self._move_to_folder("")
        )
        
        # 显示菜单
        move_menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
    
    def _move_to_folder(self, folder_name: str):
        """移动阵列到指定文件夹"""
        if self._selected_array_id:
            if self.array_manager.move_array_to_folder(self._selected_array_id, folder_name):
                self._refresh_array_list()
    
    # ==================== 阵列操作 ====================
    
    def _add_array(self):
        """添加阵列"""
        dialog = LoginDialog(self.root, folders=self.array_manager.get_folders())
        result = dialog.show()
        
        if result:
            # 生成唯一 ID
            import time
            array_id = f"array_{int(time.time() * 1000)}"
            
            config = ArrayConfig(
                id=array_id,
                name=result['name'],
                host=result['host'],
                port=result.get('port', 22),
                username=result['username'],
                password=result.get('password', ''),
                key_path=result.get('key_path', ''),
                folder=result.get('folder', ''),
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
        # 保存配置
        if self.array_manager._save_config():
            logger.info("退出前配置已保存")
        else:
            logger.warning("退出前配置保存失败")
        
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
