"""
Agent package distribution endpoints.
"""

import hashlib
import tarfile
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..config import __version__

router = APIRouter(prefix="/agent", tags=["agent-package"])

_PACKAGE_CACHE = {
    "signature": None,
    "path": "",
    "hash": "",
}


def _agent_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "agent"


def _compute_signature(root: Path) -> str:
    hasher = hashlib.sha256()
    files = sorted(
        p for p in root.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    )
    for p in files:
        st = p.stat()
        rel = p.relative_to(root).as_posix()
        hasher.update(rel.encode("utf-8"))
        hasher.update(str(st.st_size).encode("ascii"))
        hasher.update(str(int(st.st_mtime_ns)).encode("ascii"))
    return hasher.hexdigest()


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _build_or_get_package() -> tuple[Path, str]:
    agent_dir = _agent_dir()
    if not agent_dir.exists():
        raise HTTPException(status_code=500, detail=f"Agent directory not found: {agent_dir}")

    signature = _compute_signature(agent_dir)
    cached_path = Path(_PACKAGE_CACHE["path"]) if _PACKAGE_CACHE.get("path") else None
    if (
        _PACKAGE_CACHE.get("signature") == signature
        and cached_path
        and cached_path.exists()
        and _PACKAGE_CACHE.get("hash")
    ):
        return cached_path, _PACKAGE_CACHE["hash"]

    package_path = Path(tempfile.gettempdir()) / "observation_points_agent_latest.tar.gz"
    with tarfile.open(package_path, "w:gz") as tar:
        tar.add(agent_dir, arcname="observation_points")
    package_hash = _sha256_file(package_path)

    _PACKAGE_CACHE["signature"] = signature
    _PACKAGE_CACHE["path"] = str(package_path)
    _PACKAGE_CACHE["hash"] = package_hash
    return package_path, package_hash


@router.get("/package-hash")
async def get_agent_package_hash():
    _, package_hash = _build_or_get_package()
    return {
        "hash": f"sha256:{package_hash}",
        "version": __version__,
    }


@router.get("/package")
async def download_agent_package():
    package_path, _ = _build_or_get_package()
    return FileResponse(
        path=str(package_path),
        media_type="application/gzip",
        filename="observation_points.tar.gz",
    )

