"""
Agent self-updater.
"""

import hashlib
import compileall
import json
import logging
import os
import shutil
import sys
import tarfile
import tempfile
import subprocess
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

HASH_FILE = Path("/etc/observation-points/.package_hash")
PENDING_FILE = Path("/etc/observation-points/.update_pending")


class AgentUpdater:
    def __init__(self, config: dict):
        self.config = config
        self._confirm_previous_update()

    def _current_package(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def _confirm_previous_update(self):
        """A new process reached core initialization, so its retained backup is safe to remove."""
        current_pkg = self._current_package()
        backup_pkg = current_pkg.with_name(f"{current_pkg.name}.bak")
        if PENDING_FILE.exists():
            shutil.rmtree(backup_pkg, ignore_errors=True)
            try:
                PENDING_FILE.unlink()
            except OSError:
                pass

    def _validate_staged_package(self, package_dir: Path) -> bool:
        required = [
            package_dir / '__init__.py',
            package_dir / '__main__.py',
            package_dir / 'core' / 'scheduler.py',
            package_dir / 'core' / 'reporter.py',
        ]
        if not all(path.exists() for path in required):
            return False
        if not compileall.compile_dir(str(package_dir), quiet=1, force=True):
            return False
        env = os.environ.copy()
        env['PYTHONPATH'] = str(package_dir.parent)
        result = subprocess.run(
            [sys.executable, '-c',
             'import observation_points; from observation_points.core.scheduler import Scheduler'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            env=env,
            universal_newlines=True,
        )
        if result.returncode != 0:
            logger.warning("Staged Agent import check failed: %s", result.stderr[-500:])
            return False
        return True

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
        argv = runtime.get("argv") or [
            "-m", "observation_points", "-c", "/etc/observation-points/config.json"
        ]
        exec_args = [python_exe] + argv
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
                if not new_pkg.exists() or not self._validate_staged_package(new_pkg):
                    logger.warning("Downloaded package failed staged validation")
                    return False

                current_pkg = self._current_package()
                backup_pkg = current_pkg.with_name(f"{current_pkg.name}.bak")
                if backup_pkg.exists():
                    shutil.rmtree(backup_pkg, ignore_errors=True)

                old_hash = self._read_local_hash()
                os.replace(str(current_pkg), str(backup_pkg))
                try:
                    shutil.copytree(new_pkg, current_pkg)
                    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
                    PENDING_FILE.write_text(remote_hash, encoding="utf-8")
                    self._write_local_hash(remote_hash)
                    logger.info("Agent updated successfully, restarting process")
                    self._restart_self()
                except Exception:
                    shutil.rmtree(current_pkg, ignore_errors=True)
                    os.replace(str(backup_pkg), str(current_pkg))
                    if old_hash:
                        self._write_local_hash(old_hash)
                    try:
                        PENDING_FILE.unlink()
                    except OSError:
                        pass
                    raise

            return True
        except Exception as e:
            logger.warning("Agent update check failed: %s", e)
            return False
