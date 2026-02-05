"""iSCSI protocol implementation for Packet Storm.

Provides iSCSI PDU construction, session management, and protocol-specific
anomaly generation per RFC 7143.
"""

from .builder import ISCSIBuilder
from .session import ISCSISession, ISCSISessionPhase, ISCSISessionError
from .anomalies import ISCSIAnomalyMixin, ISCSI_ANOMALIES
from .pdu import (
    ISCSI_Login_Request,
    ISCSI_SCSI_Command,
    ISCSI_Data_Out,
    ISCSI_NOP_Out,
    ISCSI_Logout_Request,
    ISCSI_Task_Management,
    ISCSI_Text_Request,
    ISCSI_SNACK_Request,
    ISCSI_PDU_TYPES,
)
from .constants import InitiatorOpcode, TargetOpcode, ScsiOpcode

from ...core.registry import protocol_registry

# Register iSCSI protocol builder
protocol_registry.register("iscsi", ISCSIBuilder)

__all__ = [
    "ISCSIBuilder",
    "ISCSISession",
    "ISCSISessionPhase",
    "ISCSISessionError",
    "ISCSIAnomalyMixin",
    "ISCSI_ANOMALIES",
    "ISCSI_Login_Request",
    "ISCSI_SCSI_Command",
    "ISCSI_Data_Out",
    "ISCSI_NOP_Out",
    "ISCSI_Logout_Request",
    "ISCSI_Task_Management",
    "ISCSI_Text_Request",
    "ISCSI_SNACK_Request",
    "ISCSI_PDU_TYPES",
    "InitiatorOpcode",
    "TargetOpcode",
    "ScsiOpcode",
]
