"""
Agent self-updater.
"""

import hashlib
import json
import logging
import os
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

HASH_FILE = Path("/etc/observation-points/.package_hash")
# 记录"上一次自更新尚未确认可用"的标记文件（JSON: backup 路径 / 目标 hash / boot_attempts）。
# 用于在新版本崩溃时自动回滚到 .bak，避免升级失败把 agent 变砖。
PENDING_UPDATE_FILE = Path("/etc/observation-points/.update_pending")
# 允许的启动尝试次数：新版本经历这么多次启动仍未确认成功即判定损坏并回滚。
_MAX_BOOT_ATTEMPTS = 2


class AgentUpdater:
    def __init__(self, config: dict):
        self.config = config

    def _base_url(self) -> str:
        push_url = ((self.config.get("reporter", {}) or {}).get("push_url") or "").strip()
        if not push_url:
            return ""
        parsed = urlparse(push_url)
        if not parsed.scheme or not parsed.netloc:
            return ""
        return f"{parsed.scheme}://{parsed.netloc}"

    def _read_local_hash(self) -> str:
        try:
            if HASH_FILE.exists():
                return HASH_FILE.read_text(encoding="utf-8").strip()
        except Exception:
            pass
        return ""

    def _write_local_hash(self, package_hash: str):
        HASH_FILE.parent.mkdir(parents=True, exist_ok=True)
        HASH_FILE.write_text(package_hash, encoding="utf-8")

    @staticmethod
    def _sha256_file(path: Path) -> str:
        hasher = hashlib.sha256()
        with path.open("rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()

    def _download(self, url: str, timeout: int = 15) -> bytes:
        req = Request(url, headers={"Accept": "application/json,application/gzip"})
        with urlopen(req, timeout=timeout) as resp:
            return resp.read()

    def _restart_self(self):
        runtime = self.config.get("_runtime", {}) or {}
        python_exe = runtime.get("python_executable") or sys.executable
        # runtime["argv"] 是 sys.argv[1:]，即模块名之后的参数（如 -c <config>）。
        # 解释器已吞掉 "-m observation_points"，所以必须显式重建，否则 execv 会把
        # 配置文件路径当成 `python -c '<config>'` 的代码执行，更新即自杀。
        argv = runtime.get("argv")
        if argv is None:
            argv = ["-c", "/etc/observation-points/config.json"]
        exec_args = [python_exe, "-m", "observation_points", *argv]
        os.execv(python_exe, exec_args)

    def check_and_apply_update(self) -> bool:
        base_url = self._base_url()
        if not base_url:
            return False

        hash_endpoint = f"{base_url}/api/agent/package-hash"
        package_endpoint = f"{base_url}/api/agent/package"
        try:
            raw = self._download(hash_endpoint, timeout=8)
            payload = json.loads(raw.decode("utf-8"))
            remote_hash = (payload.get("hash") or "").replace("sha256:", "").strip()
            if not remote_hash:
                return False
            local_hash = self._read_local_hash()
            if local_hash and local_hash == remote_hash:
                return False

            package_bytes = self._download(package_endpoint, timeout=30)
            with tempfile.TemporaryDirectory(prefix="agent_update_") as td:
                tmp_dir = Path(td)
                package_path = tmp_dir / "observation_points.tar.gz"
                package_path.write_bytes(package_bytes)
                downloaded_hash = self._sha256_file(package_path)
                if downloaded_hash != remote_hash:
                    logger.warning("Update package hash mismatch: expected=%s actual=%s", remote_hash, downloaded_hash)
                    return False

                extract_dir = tmp_dir / "extract"
                extract_dir.mkdir(parents=True, exist_ok=True)
                with tarfile.open(package_path, "r:gz") as tar:
                    tar.extractall(extract_dir)
                new_pkg = extract_dir / "observation_points"
                if not new_pkg.exists():
                    logger.warning("Downloaded package missing observation_points directory")
                    return False

                current_pkg = Path(__file__).resolve().parents[1]
                backup_pkg = current_pkg.with_name(f"{current_pkg.name}.bak")
                if backup_pkg.exists():
                    shutil.rmtree(backup_pkg, ignore_errors=True)

                # 将旧版本移到 .bak（备份），再把新版本拷贝到位。
                # 关键：这里【不再】立即删除 .bak、也【不】写入 remote_hash。
                # 备份必须保留到新版本"确认能启动"之后（见 register_boot/confirm_update），
                # 否则新代码一启动就崩时已无备份可回滚，agent 直接变砖。
                os.replace(str(current_pkg), str(backup_pkg))
                shutil.copytree(new_pkg, current_pkg)

            # 写下"待确认更新"标记：记录备份路径与目标 hash，boot_attempts 从 0 计。
            # 收尾（删 .bak / 写 hash / 清标记）交给新进程启动后的 confirm_update()，
            # 若新版本反复启动失败则由 register_boot() 自动回滚。
            self._write_pending({
                "backup": str(backup_pkg),
                "hash": remote_hash,
                "boot_attempts": 0,
            })
            logger.info("Agent updated, restarting to confirm new version")
            self._restart_self()
            return True
        except Exception as e:
            logger.warning("Agent update check failed: %s", e)
            return False

    # ------------------------------------------------------------------
    # 自更新启动确认 / 自动回滚
    #
    # 完整流程（防变砖）：
    #   1. check_and_apply_update() 保留 .bak，写 .update_pending 标记后 execv 重启。
    #   2. 新版本启动 → 调度器调用 register_boot()：
    #        - boot_attempts <= _MAX_BOOT_ATTEMPTS：视为可能的正常首启，继续运行；
    #          主循环首次成功迭代后调用 confirm_update() 删 .bak、写 hash、清标记。
    #        - boot_attempts >  _MAX_BOOT_ATTEMPTS：说明新版本被反复拉起却始终没能
    #          确认（通常是一启动就崩），判定损坏，从 .bak 回滚并 re-exec 回旧版本。
    # 正常无更新时这些方法均为空操作，不影响常规启动。
    # ------------------------------------------------------------------
    def _read_pending(self) -> dict:
        try:
            if PENDING_UPDATE_FILE.exists():
                return json.loads(PENDING_UPDATE_FILE.read_text(encoding="utf-8")) or {}
        except Exception:
            pass
        return {}

    def _write_pending(self, info: dict) -> None:
        PENDING_UPDATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        PENDING_UPDATE_FILE.write_text(json.dumps(info), encoding="utf-8")

    def _clear_pending(self) -> None:
        try:
            PENDING_UPDATE_FILE.unlink()
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning("清理更新标记失败: %s", e)

    def register_boot(self) -> None:
        """调度器启动时调用：累加启动计数，必要时回滚。见上方流程说明。"""
        info = self._read_pending()
        if not info:
            return
        attempts = int(info.get("boot_attempts", 0)) + 1
        info["boot_attempts"] = attempts
        if attempts > _MAX_BOOT_ATTEMPTS:
            logger.error("新版本已启动 %d 次仍未确认，判定为损坏，开始回滚", attempts)
            self._rollback(info)
            return
        self._write_pending(info)
        logger.warning(
            "检测到待确认的自更新（第 %d 次启动）；主循环稳定后将确认，否则将回滚", attempts
        )

    def confirm_update(self) -> None:
        """新版本成功启动（主循环已跑起来）后调用：删 .bak、写 hash、清标记。"""
        info = self._read_pending()
        if not info:
            return
        backup = info.get("backup")
        if backup:
            shutil.rmtree(backup, ignore_errors=True)
        target_hash = info.get("hash")
        if target_hash:
            try:
                self._write_local_hash(target_hash)
            except Exception as e:
                logger.warning("写入 package hash 失败: %s", e)
        self._clear_pending()
        logger.info("自更新已确认成功，已清理备份: %s", backup)

    def _rollback(self, info: dict) -> None:
        current_pkg = Path(__file__).resolve().parents[1]
        self._rollback_to(info.get("backup"), str(current_pkg))

    def _rollback_to(self, backup, current_pkg) -> None:
        """从 backup 目录回滚到 current_pkg 位置，清标记并 re-exec。"""
        try:
            if not backup or not Path(backup).exists():
                logger.error("待回滚的备份不存在(%s)，无法回滚；清理标记以避免死循环", backup)
                self._clear_pending()
                return
            current = Path(current_pkg)
            logger.error("从备份回滚: %s -> %s", backup, current)
            broken = current.with_name(f"{current.name}.broken")
            shutil.rmtree(broken, ignore_errors=True)
            os.replace(str(current), str(broken))        # 把损坏的新版本挪开
            os.replace(str(backup), str(current))         # 备份就位为当前版本
            shutil.rmtree(broken, ignore_errors=True)     # 丢弃损坏版本
            self._clear_pending()
            logger.info("回滚完成，重启回旧版本")
            self._restart_self()
        except Exception as e:
            logger.error("回滚失败: %s", e)
            self._clear_pending()

