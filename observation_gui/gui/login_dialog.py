"""
登录对话框

用于添加新阵列时输入连接信息。
"""

import tkinter as tk
from tkinter import ttk, filedialog
from typing import Any, Dict, Optional


class LoginDialog:
    """
    登录对话框
    
    收集阵列连接信息：
    - 名称
    - 主机地址
    - 端口
    - 用户名
    - 密码 / 密钥文件
    """
    
    def __init__(self, parent: tk.Tk):
        """
        初始化对话框
        
        Args:
            parent: 父窗口
        """
        self.parent = parent
        self.result = None  # type: Optional[Dict[str, Any]]
        
        # 创建对话框窗口
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("添加阵列")
        self.dialog.geometry("400x350")
        self.dialog.resizable(False, False)
        
        # 模态
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        # 居中显示
        self._center_window()
        
        # 构建界面
        self._build_ui()
        
        # 绑定事件
        self.dialog.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.dialog.bind('<Return>', lambda e: self._on_ok())
        self.dialog.bind('<Escape>', lambda e: self._on_cancel())
    
    def _center_window(self):
        """居中显示"""
        self.dialog.update_idletasks()
        
        width = self.dialog.winfo_width()
        height = self.dialog.winfo_height()
        
        parent_x = self.parent.winfo_x()
        parent_y = self.parent.winfo_y()
        parent_width = self.parent.winfo_width()
        parent_height = self.parent.winfo_height()
        
        x = parent_x + (parent_width - width) // 2
        y = parent_y + (parent_height - height) // 2
        
        self.dialog.geometry(f"+{x}+{y}")
    
    def _build_ui(self):
        """构建界面"""
        # 主框架
        main_frame = ttk.Frame(self.dialog, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 名称
        row = 0
        ttk.Label(main_frame, text="阵列名称:").grid(
            row=row, column=0, sticky=tk.W, pady=5
        )
        self.name_var = tk.StringVar()
        self.name_entry = ttk.Entry(main_frame, textvariable=self.name_var, width=30)
        self.name_entry.grid(row=row, column=1, sticky=tk.W, pady=5)
        
        # 主机地址
        row += 1
        ttk.Label(main_frame, text="主机地址:").grid(
            row=row, column=0, sticky=tk.W, pady=5
        )
        self.host_var = tk.StringVar()
        self.host_entry = ttk.Entry(main_frame, textvariable=self.host_var, width=30)
        self.host_entry.grid(row=row, column=1, sticky=tk.W, pady=5)
        
        # 端口
        row += 1
        ttk.Label(main_frame, text="SSH 端口:").grid(
            row=row, column=0, sticky=tk.W, pady=5
        )
        self.port_var = tk.StringVar(value="22")
        self.port_entry = ttk.Entry(main_frame, textvariable=self.port_var, width=10)
        self.port_entry.grid(row=row, column=1, sticky=tk.W, pady=5)
        
        # 用户名
        row += 1
        ttk.Label(main_frame, text="用户名:").grid(
            row=row, column=0, sticky=tk.W, pady=5
        )
        self.user_var = tk.StringVar(value="root")
        self.user_entry = ttk.Entry(main_frame, textvariable=self.user_var, width=30)
        self.user_entry.grid(row=row, column=1, sticky=tk.W, pady=5)
        
        # 认证方式
        row += 1
        ttk.Label(main_frame, text="认证方式:").grid(
            row=row, column=0, sticky=tk.W, pady=5
        )
        
        self.auth_type_var = tk.StringVar(value="password")
        auth_frame = ttk.Frame(main_frame)
        auth_frame.grid(row=row, column=1, sticky=tk.W, pady=5)
        
        ttk.Radiobutton(
            auth_frame, text="密码", 
            variable=self.auth_type_var, value="password",
            command=self._on_auth_type_change
        ).pack(side=tk.LEFT)
        
        ttk.Radiobutton(
            auth_frame, text="密钥文件",
            variable=self.auth_type_var, value="key",
            command=self._on_auth_type_change
        ).pack(side=tk.LEFT, padx=(10, 0))
        
        # 密码
        row += 1
        self.password_label = ttk.Label(main_frame, text="密码:")
        self.password_label.grid(row=row, column=0, sticky=tk.W, pady=5)
        
        self.password_var = tk.StringVar()
        self.password_entry = ttk.Entry(
            main_frame, textvariable=self.password_var, 
            width=30, show='*'
        )
        self.password_entry.grid(row=row, column=1, sticky=tk.W, pady=5)
        
        # 密钥文件（初始隐藏）
        row += 1
        self.key_label = ttk.Label(main_frame, text="密钥文件:")
        self.key_var = tk.StringVar()
        
        key_frame = ttk.Frame(main_frame)
        self.key_entry = ttk.Entry(key_frame, textvariable=self.key_var, width=22)
        self.key_entry.pack(side=tk.LEFT)
        
        self.key_browse_btn = ttk.Button(
            key_frame, text="浏览...", 
            command=self._browse_key_file,
            width=8
        )
        self.key_browse_btn.pack(side=tk.LEFT, padx=(5, 0))
        
        self.key_frame = key_frame
        
        # 初始隐藏密钥相关控件
        self.key_label.grid(row=row, column=0, sticky=tk.W, pady=5)
        self.key_frame.grid(row=row, column=1, sticky=tk.W, pady=5)
        self.key_label.grid_remove()
        self.key_frame.grid_remove()
        
        # 按钮
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=row+1, column=0, columnspan=2, pady=20)
        
        ttk.Button(btn_frame, text="确定", command=self._on_ok, width=10).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(btn_frame, text="取消", command=self._on_cancel, width=10).pack(
            side=tk.LEFT, padx=5
        )
        
        # 聚焦到名称输入框
        self.name_entry.focus_set()
    
    def _on_auth_type_change(self):
        """认证方式切换"""
        if self.auth_type_var.get() == "password":
            self.password_label.grid()
            self.password_entry.grid()
            self.key_label.grid_remove()
            self.key_frame.grid_remove()
        else:
            self.password_label.grid_remove()
            self.password_entry.grid_remove()
            self.key_label.grid()
            self.key_frame.grid()
    
    def _browse_key_file(self):
        """浏览密钥文件"""
        filename = filedialog.askopenfilename(
            parent=self.dialog,
            title="选择私钥文件",
            filetypes=[
                ("所有文件", "*.*"),
                ("PEM 文件", "*.pem"),
                ("私钥文件", "id_rsa"),
            ],
            initialdir="~/.ssh"
        )
        if filename:
            self.key_var.set(filename)
    
    def _validate(self) -> bool:
        """验证输入"""
        if not self.name_var.get().strip():
            self._show_error("请输入阵列名称")
            self.name_entry.focus_set()
            return False
        
        if not self.host_var.get().strip():
            self._show_error("请输入主机地址")
            self.host_entry.focus_set()
            return False
        
        try:
            port = int(self.port_var.get())
            if port < 1 or port > 65535:
                raise ValueError()
        except ValueError:
            self._show_error("端口必须是 1-65535 之间的数字")
            self.port_entry.focus_set()
            return False
        
        if not self.user_var.get().strip():
            self._show_error("请输入用户名")
            self.user_entry.focus_set()
            return False
        
        if self.auth_type_var.get() == "password":
            if not self.password_var.get():
                self._show_error("请输入密码")
                self.password_entry.focus_set()
                return False
        else:
            if not self.key_var.get().strip():
                self._show_error("请选择密钥文件")
                return False
        
        return True
    
    def _show_error(self, message: str):
        """显示错误信息"""
        from tkinter import messagebox
        messagebox.showerror("输入错误", message, parent=self.dialog)
    
    def _on_ok(self):
        """确定按钮"""
        if not self._validate():
            return
        
        self.result = {
            'name': self.name_var.get().strip(),
            'host': self.host_var.get().strip(),
            'port': int(self.port_var.get()),
            'username': self.user_var.get().strip(),
        }
        
        if self.auth_type_var.get() == "password":
            self.result['password'] = self.password_var.get()
        else:
            self.result['key_path'] = self.key_var.get().strip()
        
        self.dialog.destroy()
    
    def _on_cancel(self):
        """取消按钮"""
        self.result = None
        self.dialog.destroy()
    
    def show(self) -> Optional[Dict[str, Any]]:
        """
        显示对话框并等待结果
        
        Returns:
            用户输入的数据，或 None（如果取消）
        """
        self.dialog.wait_window()
        return self.result
