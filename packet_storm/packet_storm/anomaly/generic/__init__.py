"""Generic anomaly types applicable to all protocols.

Import all anomaly modules to trigger registration.
"""

from .field_tamper import FieldTamperAnomaly
from .truncation import TruncationAnomaly
from .padding import PaddingAnomaly
from .checksum import ChecksumErrorAnomaly
from .replay import ReplayAnomaly
from .malformed import MalformedAnomaly
from .fragmentation import FragmentationAnomaly
from .sequence import SequenceAnomaly
from .flood import FloodAnomaly

__all__ = [
    "FieldTamperAnomaly",
    "TruncationAnomaly",
    "PaddingAnomaly",
    "ChecksumErrorAnomaly",
    "ReplayAnomaly",
    "MalformedAnomaly",
    "FragmentationAnomaly",
    "SequenceAnomaly",
    "FloodAnomaly",
]
