"""
In-memory array status cache.

Lives in ``core`` (not ``api``) so that low-level services such as
``core/alert_sync.py`` and ``core/runtime_status.py`` can read/write the shared
status store without importing the ``api`` layer — that reverse dependency was
the root cause of the core->api coupling and the function-body import churn.

``api/array_status.py`` and ``api/arrays.py`` re-export these symbols for
backward compatibility, so existing ``from .array_status import ...`` /
``from .arrays import ...`` call sites keep working unchanged.
"""
from typing import Dict

from ..models.array import ArrayStatus

# The single global in-memory status store.
_array_status_cache: Dict[str, ArrayStatus] = {}


def _get_array_status(array_id: str) -> ArrayStatus:
    """Get or create array status from the in-memory cache."""
    if array_id not in _array_status_cache:
        _array_status_cache[array_id] = ArrayStatus(array_id=array_id, name="", host="")
    return _array_status_cache[array_id]
