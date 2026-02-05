"""Anomaly generation engine for Packet Storm.

Provides generic and protocol-specific anomaly generators that can
mutate valid packets into abnormal/malicious variants.
"""

from .base import BaseAnomaly
from .registry import register_anomaly, create_anomaly, list_anomalies

# Import generic anomalies to trigger their registration
from .generic import (
    FieldTamperAnomaly,
    TruncationAnomaly,
    PaddingAnomaly,
    ChecksumErrorAnomaly,
    ReplayAnomaly,
    MalformedAnomaly,
    FragmentationAnomaly,
    SequenceAnomaly,
    FloodAnomaly,
)

__all__ = [
    "BaseAnomaly",
    "register_anomaly",
    "create_anomaly",
    "list_anomalies",
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
