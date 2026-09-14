# Windows 便携包

适用 Windows 10/11 x64。解压到可写目录，双击 `Start.bat`，服务就绪后自动打开浏览器。运行时已包含 Python 和依赖。首次登录使用初始管理员 `admin / admin123`，使用前在 `config.json` 的 `admin.password` 中修改密码。按 Ctrl+C 停止服务。

配置在 `config.json`：`server.port` 决定访问端口。默认仅本机访问；需要远程设备主动推送数据时，将 `server.host` 设置为 `0.0.0.0`，在防火墙放行配置端口，并将 `remote.ingest_url` 设置为设备能访问的地址。

数据库保存在 `data/observation_web.db`，日志保存在 `logs/platform.log`。升级时先停止服务、备份旧目录，将原 `config.json` 和 `data` 复制到新包，再启动。不要同时运行两个使用同一数据库的实例。

## 构建

在 Windows x64 上安装 Python 3.13 x64、Node.js 22 和 Git，检出仓库后运行：

```powershell
powershell -ExecutionPolicy Bypass -File observation_web/scripts/build-windows.ps1
```

输出到 `observation_web/dist/`：便携 ZIP 和 SHA-256 校验文件。构建阶段需要网络。内置运行环境来自 Python 官方 Windows embeddable 3.13.12；脚本校验固定 SHA-256。依赖解析结果记录在包内 `BUILD.json`。

GitHub Actions 的 **Windows portable package** 支持手动运行；成功后在该次运行的 Artifacts 中下载 `observation-platform-windows-x64`。先解压下载的 artifact，再解压其中的便携 ZIP。

构建检查使用解压后的内置 Python，在包含中文和空格的路径下启动，验证页面、静态资源、拓扑接口、数据库迁移及重启后的数据保留。检查结束后才发布 artifact。现场 SSH 登录和设备采集仍需在目标网络验证。
