"""
Agent package distribution endpoints.
"""

import gzip
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


def _iter_agent_files(root: Path):
    """Deterministically ordered list of packaged agent files (no pyc/pycache)."""
    return sorted(
        p for p in root.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    )


def _compute_signature(root: Path) -> str:
    """Content-based signature — stable across backend restarts and file mtime
    changes.  Used as BOTH the cache key and the public package hash.

    The old signature hashed st_mtime_ns, so a backend restart rebuilt the
    tarball with a fresh gzip mtime, changed its sha256, and made every agent
    think a new version existed → fleet-wide pointless self-update + restart.
    Hashing file *content* removes that: the hash only changes when code changes.
    """
    hasher = hashlib.sha256()
    for p in _iter_agent_files(root):
        rel = p.relative_to(root).as_posix()
        hasher.update(rel.encode("utf-8"))
        hasher.update(b"\0")
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                hasher.update(chunk)
        hasher.update(b"\0")
    return hasher.hexdigest()


def _write_reproducible_package(agent_dir: Path, package_path: Path) -> None:
    """Write a byte-for-byte reproducible tar.gz (gzip mtime=0, normalized members)."""
    with package_path.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w") as tar:
                for p in _iter_agent_files(agent_dir):
                    arcname = "observation_points/" + p.relative_to(agent_dir).as_posix()
                    ti = tar.gettarinfo(str(p), arcname=arcname)
                    ti.mtime = 0
                    ti.uid = ti.gid = 0
                    ti.uname = ti.gname = ""
                    with p.open("rb") as f:
                        tar.addfile(ti, f)


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
    _write_reproducible_package(agent_dir, package_path)

    # Public hash is the CONTENT signature, not the tarball's sha256, so it stays
    # stable across backend restarts (the tarball is reproducible anyway).
    _PACKAGE_CACHE["signature"] = signature
    _PACKAGE_CACHE["path"] = str(package_path)
    _PACKAGE_CACHE["hash"] = signature
    return package_path, signature


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

