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
        argv = runtime.get("argv") or [
            "-m", "observation_points", "-c", "/etc/observation-points/config.json"
        ]
        if argv and argv[0] != "-m":
            exec_args = [python_exe] + argv
        else:
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
                if not new_pkg.exists():
                    logger.warning("Downloaded package missing observation_points directory")
                    return False

                current_pkg = Path(__file__).resolve().parents[1]
                backup_pkg = current_pkg.with_name(f"{current_pkg.name}.bak")
                if backup_pkg.exists():
                    shutil.rmtree(backup_pkg, ignore_errors=True)

                os.replace(str(current_pkg), str(backup_pkg))
                shutil.copytree(new_pkg, current_pkg)
                shutil.rmtree(backup_pkg, ignore_errors=True)

            self._write_local_hash(remote_hash)
            logger.info("Agent updated successfully, restarting process")
            self._restart_self()
            return True
        except Exception as e:
            logger.warning("Agent update check failed: %s", e)
            return False

