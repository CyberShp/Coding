"""iSCSI PDU (Protocol Data Unit) definitions as Scapy layers.

Implements the iSCSI Basic Header Segment (BHS) and all initiator PDU types
per RFC 7143 for packet construction and manipulation.
"""

import struct
from scapy.packet import Packet, bind_layers
from scapy.fields import (
    ByteField,
    ByteEnumField,
    BitField,
    BitEnumField,
    ShortField,
    IntField,
    XIntField,
    XByteField,
    StrFixedLenField,
    StrLenField,
    FieldLenField,
    ConditionalField,
    PacketLenField,
    FlagsField,
    LenField,
    LEIntField,
)

from .constants import (
    InitiatorOpcode,
    TargetOpcode,
    BHS_SIZE,
    BHS_CDB_LENGTH,
    LOGIN_STAGE_SECURITY_NEGOTIATION,
    LOGIN_STAGE_OPERATIONAL_NEGOTIATION,
    LOGIN_STAGE_FULL_FEATURE,
)


# =============================================================================
# iSCSI Basic Header Segment (48 bytes)
# =============================================================================

class ISCSI_BHS(Packet):
    """iSCSI Basic Header Segment - the common 48-byte header for all PDUs.

    This is the base layer that all iSCSI PDU types build upon.
    The opcode field determines the type of PDU and the interpretation
    of the remaining header fields.
    """
    name = "iSCSI BHS"
    fields_desc = [
        # Byte 0: opcode (6 bits) + immediate flag (1 bit) + reserved (1 bit)
        BitField("reserved1", 0, 1),
        BitField("immediate", 0, 1),
        BitField("opcode", 0, 6),
        # Byte 1: opcode-specific flags
        ByteField("flags", 0),
        # Bytes 2-3: opcode-specific
        ShortField("opcode_specific", 0),
        # Bytes 4-7: Total AHS (Additional Header Segment) length + Data Segment Length
        ByteField("total_ahs_length", 0),
        BitField("data_segment_length", 0, 24),
        # Bytes 8-15: LUN or opcode-specific
        StrFixedLenField("lun", b"\x00" * 8, 8),
        # Bytes 16-19: Initiator Task Tag
        XIntField("itt", 0),
        # Bytes 20-47: opcode-specific fields (28 bytes)
        StrFixedLenField("opcode_specific_fields", b"\x00" * 28, 28),
    ]

    def post_build(self, pkt: bytes, pay: bytes) -> bytes:
        """Auto-calculate data segment length if not set."""
        if self.data_segment_length == 0 and pay:
            # Update data segment length in bytes 5-7
            length = len(pay)
            pkt = pkt[:5] + struct.pack("!I", length)[1:] + pkt[8:]
        return pkt + pay


# =============================================================================
# iSCSI Login Request PDU
# =============================================================================

class ISCSI_Login_Request(Packet):
    """iSCSI Login Request PDU (Opcode 0x03).

    Used during session establishment to negotiate parameters between
    initiator and target. Supports security and operational negotiation.
    """
    name = "iSCSI Login Request"
    fields_desc = [
        # Byte 0
        BitField("reserved1", 0, 1),
        BitField("immediate", 1, 1),  # Login is always immediate
        BitField("opcode", InitiatorOpcode.LOGIN_REQUEST, 6),
        # Byte 1: flags
        BitField("transit", 0, 1),    # Transit to next stage
        BitField("continue_flag", 0, 1),  # Continue current stage
        BitField("reserved2", 0, 2),
        BitField("csg", LOGIN_STAGE_SECURITY_NEGOTIATION, 2),  # Current stage
        BitField("nsg", LOGIN_STAGE_OPERATIONAL_NEGOTIATION, 2),  # Next stage
        # Byte 2: version max
        ByteField("version_max", 0x00),
        # Byte 3: version min
        ByteField("version_min", 0x00),
        # Bytes 4-7: Total AHS length + Data segment length
        ByteField("total_ahs_length", 0),
        BitField("data_segment_length", 0, 24),
        # Bytes 8-15: ISID (6 bytes) + TSIH (2 bytes)
        XIntField("isid_a", 0x00023D00),  # Type + OUI
        ShortField("isid_b", 0x0000),     # Qualifier
        ShortField("tsih", 0x0000),       # Target Session Identifying Handle
        # Bytes 16-19: Initiator Task Tag
        XIntField("itt", 0x00000001),
        # Bytes 20-21: Connection ID
        ShortField("cid", 0x0001),
        # Bytes 22-23: Reserved
        ShortField("reserved3", 0),
        # Bytes 24-27: CmdSN
        IntField("cmdsn", 1),
        # Bytes 28-31: ExpStatSN
        IntField("expstatsn", 0),
        # Bytes 32-47: Reserved (16 bytes)
        StrFixedLenField("reserved4", b"\x00" * 16, 16),
    ]

    def post_build(self, pkt: bytes, pay: bytes) -> bytes:
        """Auto-calculate data segment length and add padding."""
        if self.data_segment_length == 0 and pay:
            length = len(pay)
            # Update data_segment_length (bytes 5-7)
            pkt = pkt[:5] + struct.pack("!I", length)[1:] + pkt[8:]

        # Pad data segment to 4-byte boundary
        if pay:
            pad_len = (4 - (len(pay) % 4)) % 4
            pay = pay + b"\x00" * pad_len

        return pkt + pay


# =============================================================================
# iSCSI SCSI Command PDU
# =============================================================================

class ISCSI_SCSI_Command(Packet):
    """iSCSI SCSI Command PDU (Opcode 0x01).

    Carries a SCSI Command Descriptor Block (CDB) from the initiator
    to the target. Supports read, write, and bidirectional operations.
    """
    name = "iSCSI SCSI Command"
    fields_desc = [
        # Byte 0
        BitField("reserved1", 0, 1),
        BitField("immediate", 0, 1),
        BitField("opcode", InitiatorOpcode.SCSI_COMMAND, 6),
        # Byte 1: flags
        BitField("final", 1, 1),
        BitField("read", 0, 1),
        BitField("write", 0, 1),
        BitField("reserved2", 0, 2),
        BitField("attr", 0, 3),  # Task attributes
        # Bytes 2-3: Reserved
        ShortField("reserved3", 0),
        # Bytes 4-7: Total AHS length + Data segment length
        ByteField("total_ahs_length", 0),
        BitField("data_segment_length", 0, 24),
        # Bytes 8-15: LUN
        StrFixedLenField("lun", b"\x00" * 8, 8),
        # Bytes 16-19: Initiator Task Tag
        XIntField("itt", 0x00000001),
        # Bytes 20-23: Expected Data Transfer Length
        IntField("expected_data_length", 0),
        # Bytes 24-27: CmdSN
        IntField("cmdsn", 1),
        # Bytes 28-31: ExpStatSN
        IntField("expstatsn", 0),
        # Bytes 32-47: CDB (16 bytes)
        StrFixedLenField("cdb", b"\x00" * BHS_CDB_LENGTH, BHS_CDB_LENGTH),
    ]

    def post_build(self, pkt: bytes, pay: bytes) -> bytes:
        """Auto-calculate data segment length and add padding."""
        if self.data_segment_length == 0 and pay:
            length = len(pay)
            pkt = pkt[:5] + struct.pack("!I", length)[1:] + pkt[8:]
        if pay:
            pad_len = (4 - (len(pay) % 4)) % 4
            pay = pay + b"\x00" * pad_len
        return pkt + pay


# =============================================================================
# iSCSI SCSI Data-Out PDU
# =============================================================================

class ISCSI_Data_Out(Packet):
    """iSCSI SCSI Data-Out PDU (Opcode 0x05).

    Carries write data from the initiator to the target, typically
    in response to an R2T (Ready to Transfer) from the target.
    """
    name = "iSCSI Data-Out"
    fields_desc = [
        # Byte 0
        BitField("reserved1", 0, 1),
        BitField("immediate", 0, 1),
        BitField("opcode", InitiatorOpcode.SCSI_DATA_OUT, 6),
        # Byte 1: flags
        BitField("final", 1, 1),
        BitField("reserved2", 0, 7),
        # Bytes 2-3: Reserved
        ShortField("reserved3", 0),
        # Bytes 4-7: Total AHS length + Data segment length
        ByteField("total_ahs_length", 0),
        BitField("data_segment_length", 0, 24),
        # Bytes 8-15: LUN
        StrFixedLenField("lun", b"\x00" * 8, 8),
        # Bytes 16-19: Initiator Task Tag
        XIntField("itt", 0x00000001),
        # Bytes 20-23: Target Transfer Tag
        XIntField("ttt", 0xFFFFFFFF),
        # Bytes 24-27: StatSN (reserved for Data-Out)
        IntField("reserved_statsn", 0),
        # Bytes 28-31: ExpStatSN
        IntField("expstatsn", 0),
        # Bytes 32-35: Reserved
        IntField("reserved4", 0),
        # Bytes 36-39: DataSN
        IntField("datasn", 0),
        # Bytes 40-43: Buffer Offset
        IntField("buffer_offset", 0),
        # Bytes 44-47: Reserved
        IntField("reserved5", 0),
    ]

    def post_build(self, pkt: bytes, pay: bytes) -> bytes:
        """Auto-calculate data segment length and add padding."""
        if self.data_segment_length == 0 and pay:
            length = len(pay)
            pkt = pkt[:5] + struct.pack("!I", length)[1:] + pkt[8:]
        if pay:
            pad_len = (4 - (len(pay) % 4)) % 4
            pay = pay + b"\x00" * pad_len
        return pkt + pay


# =============================================================================
# iSCSI NOP-Out PDU
# =============================================================================

class ISCSI_NOP_Out(Packet):
    """iSCSI NOP-Out PDU (Opcode 0x00).

    Used for connection keepalive and ping. Can be sent as a solicited
    response to a NOP-In or unsolicited by the initiator.
    """
    name = "iSCSI NOP-Out"
    fields_desc = [
        # Byte 0
        BitField("reserved1", 0, 1),
        BitField("immediate", 1, 1),
        BitField("opcode", InitiatorOpcode.NOP_OUT, 6),
        # Byte 1: flags
        BitField("final", 1, 1),
        BitField("reserved2", 0, 7),
        # Bytes 2-3: Reserved
        ShortField("reserved3", 0),
        # Bytes 4-7: Total AHS length + Data segment length
        ByteField("total_ahs_length", 0),
        BitField("data_segment_length", 0, 24),
        # Bytes 8-15: LUN
        StrFixedLenField("lun", b"\x00" * 8, 8),
        # Bytes 16-19: Initiator Task Tag
        XIntField("itt", 0x00000001),
        # Bytes 20-23: Target Transfer Tag
        XIntField("ttt", 0xFFFFFFFF),
        # Bytes 24-27: CmdSN
        IntField("cmdsn", 1),
        # Bytes 28-31: ExpStatSN
        IntField("expstatsn", 0),
        # Bytes 32-47: Reserved (16 bytes)
        StrFixedLenField("reserved4", b"\x00" * 16, 16),
    ]


# =============================================================================
# iSCSI Logout Request PDU
# =============================================================================

class ISCSI_Logout_Request(Packet):
    """iSCSI Logout Request PDU (Opcode 0x06).

    Used to close a session or connection gracefully.
    """
    name = "iSCSI Logout Request"
    fields_desc = [
        # Byte 0
        BitField("reserved1", 0, 1),
        BitField("immediate", 1, 1),
        BitField("opcode", InitiatorOpcode.LOGOUT_REQUEST, 6),
        # Byte 1: flags + reason code
        BitField("final", 1, 1),
        BitField("reason_code", 0, 7),  # 0=close session, 1=close conn, 2=recovery
        # Bytes 2-3: Reserved
        ShortField("reserved2", 0),
        # Bytes 4-7: Total AHS length + Data segment length
        ByteField("total_ahs_length", 0),
        BitField("data_segment_length", 0, 24),
        # Bytes 8-15: Reserved
        StrFixedLenField("reserved3", b"\x00" * 8, 8),
        # Bytes 16-19: Initiator Task Tag
        XIntField("itt", 0x00000001),
        # Bytes 20-21: CID (for close connection)
        ShortField("cid", 0x0001),
        # Bytes 22-23: Reserved
        ShortField("reserved4", 0),
        # Bytes 24-27: CmdSN
        IntField("cmdsn", 1),
        # Bytes 28-31: ExpStatSN
        IntField("expstatsn", 0),
        # Bytes 32-47: Reserved (16 bytes)
        StrFixedLenField("reserved5", b"\x00" * 16, 16),
    ]


# =============================================================================
# iSCSI Task Management Request PDU
# =============================================================================

class ISCSI_Task_Management(Packet):
    """iSCSI Task Management Request PDU (Opcode 0x02).

    Used to manage outstanding SCSI tasks (abort, LUN reset, etc.).
    """
    name = "iSCSI Task Management"
    fields_desc = [
        # Byte 0
        BitField("reserved1", 0, 1),
        BitField("immediate", 1, 1),
        BitField("opcode", InitiatorOpcode.TASK_MANAGEMENT, 6),
        # Byte 1: flags + function code
        BitField("final", 1, 1),
        BitField("function", 0, 7),
        # Bytes 2-3: Reserved
        ShortField("reserved2", 0),
        # Bytes 4-7: Total AHS length + Data segment length
        ByteField("total_ahs_length", 0),
        BitField("data_segment_length", 0, 24),
        # Bytes 8-15: LUN
        StrFixedLenField("lun", b"\x00" * 8, 8),
        # Bytes 16-19: Initiator Task Tag
        XIntField("itt", 0x00000001),
        # Bytes 20-23: Referenced Task Tag
        XIntField("ref_task_tag", 0xFFFFFFFF),
        # Bytes 24-27: CmdSN
        IntField("cmdsn", 1),
        # Bytes 28-31: ExpStatSN
        IntField("expstatsn", 0),
        # Bytes 32-35: RefCmdSN
        IntField("ref_cmdsn", 0),
        # Bytes 36-39: ExpDataSN
        IntField("exp_datasn", 0),
        # Bytes 40-47: Reserved (8 bytes)
        StrFixedLenField("reserved3", b"\x00" * 8, 8),
    ]


# =============================================================================
# iSCSI Text Request PDU
# =============================================================================

class ISCSI_Text_Request(Packet):
    """iSCSI Text Request PDU (Opcode 0x04).

    Used for parameter negotiation and target discovery after login.
    """
    name = "iSCSI Text Request"
    fields_desc = [
        # Byte 0
        BitField("reserved1", 0, 1),
        BitField("immediate", 1, 1),
        BitField("opcode", InitiatorOpcode.TEXT_REQUEST, 6),
        # Byte 1: flags
        BitField("final", 1, 1),
        BitField("continue_flag", 0, 1),
        BitField("reserved2", 0, 6),
        # Bytes 2-3: Reserved
        ShortField("reserved3", 0),
        # Bytes 4-7: Total AHS length + Data segment length
        ByteField("total_ahs_length", 0),
        BitField("data_segment_length", 0, 24),
        # Bytes 8-15: LUN
        StrFixedLenField("lun", b"\x00" * 8, 8),
        # Bytes 16-19: Initiator Task Tag
        XIntField("itt", 0x00000001),
        # Bytes 20-23: Target Transfer Tag
        XIntField("ttt", 0xFFFFFFFF),
        # Bytes 24-27: CmdSN
        IntField("cmdsn", 1),
        # Bytes 28-31: ExpStatSN
        IntField("expstatsn", 0),
        # Bytes 32-47: Reserved (16 bytes)
        StrFixedLenField("reserved4", b"\x00" * 16, 16),
    ]

    def post_build(self, pkt: bytes, pay: bytes) -> bytes:
        """Auto-calculate data segment length and add padding."""
        if self.data_segment_length == 0 and pay:
            length = len(pay)
            pkt = pkt[:5] + struct.pack("!I", length)[1:] + pkt[8:]
        if pay:
            pad_len = (4 - (len(pay) % 4)) % 4
            pay = pay + b"\x00" * pad_len
        return pkt + pay


# =============================================================================
# iSCSI SNACK Request PDU
# =============================================================================

class ISCSI_SNACK_Request(Packet):
    """iSCSI SNACK Request PDU (Opcode 0x10).

    Used to request retransmission of specific data or status PDUs.
    """
    name = "iSCSI SNACK Request"
    fields_desc = [
        # Byte 0
        BitField("reserved1", 0, 1),
        BitField("immediate", 0, 1),
        BitField("opcode", InitiatorOpcode.SNACK_REQUEST, 6),
        # Byte 1: flags + SNACK type
        BitField("final", 1, 1),
        BitField("reserved2", 0, 3),
        BitField("snack_type", 0, 4),
        # Bytes 2-3: Reserved
        ShortField("reserved3", 0),
        # Bytes 4-7: Total AHS length + Data segment length
        ByteField("total_ahs_length", 0),
        BitField("data_segment_length", 0, 24),
        # Bytes 8-15: LUN
        StrFixedLenField("lun", b"\x00" * 8, 8),
        # Bytes 16-19: Initiator Task Tag
        XIntField("itt", 0x00000001),
        # Bytes 20-23: Target Transfer Tag or SNACK Tag
        XIntField("ttt", 0xFFFFFFFF),
        # Bytes 24-27: Reserved
        IntField("reserved4", 0),
        # Bytes 28-31: ExpStatSN
        IntField("expstatsn", 0),
        # Bytes 32-47: Reserved (16 bytes)
        StrFixedLenField("reserved5", b"\x00" * 16, 16),
    ]


# =============================================================================
# PDU type lookup
# =============================================================================

ISCSI_PDU_TYPES = {
    "login_request": ISCSI_Login_Request,
    "scsi_command": ISCSI_SCSI_Command,
    "data_out": ISCSI_Data_Out,
    "nop_out": ISCSI_NOP_Out,
    "logout_request": ISCSI_Logout_Request,
    "task_management": ISCSI_Task_Management,
    "text_request": ISCSI_Text_Request,
    "snack_request": ISCSI_SNACK_Request,
}
