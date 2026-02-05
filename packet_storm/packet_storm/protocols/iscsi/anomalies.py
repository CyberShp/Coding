"""iSCSI-specific anomaly definitions.

These anomalies target iSCSI protocol-specific fields and behaviors
that go beyond generic packet manipulation.
"""

import random
import struct
from typing import Any, Optional

from scapy.packet import Packet, Raw

from .constants import (
    InitiatorOpcode,
    TargetOpcode,
    ALL_OPCODES,
    RESERVED_TAG,
    LOGIN_STAGE_FULL_FEATURE,
)
from .pdu import (
    ISCSI_Login_Request,
    ISCSI_SCSI_Command,
    ISCSI_Data_Out,
    ISCSI_NOP_Out,
    ISCSI_Logout_Request,
)
from ...utils.logging import get_logger

logger = get_logger("protocol.iscsi.anomalies")


class ISCSIAnomalyMixin:
    """Mixin providing iSCSI-specific anomaly application methods.

    These methods can be used by anomaly generators to apply
    iSCSI-specific mutations to packets.
    """

    @staticmethod
    def invalid_opcode(packet: Packet) -> Packet:
        """Replace the iSCSI opcode with an invalid value.

        Uses opcodes that are either undefined or belong to the wrong
        direction (e.g., target opcodes from initiator).
        """
        # Generate an opcode that's not in the valid set
        valid_opcodes = set(ALL_OPCODES.keys())
        while True:
            bad_opcode = random.randint(0, 0x3F)
            if bad_opcode not in valid_opcodes:
                break

        return _set_iscsi_field(packet, "opcode", bad_opcode)

    @staticmethod
    def wrong_direction_opcode(packet: Packet) -> Packet:
        """Replace initiator opcode with a target opcode.

        Sends target-only opcodes (like SCSI Response, R2T) from the
        initiator side, which should be rejected.
        """
        target_opcodes = list(TargetOpcode.ALL.keys())
        bad_opcode = random.choice(target_opcodes)
        return _set_iscsi_field(packet, "opcode", bad_opcode)

    @staticmethod
    def invalid_itt(packet: Packet) -> Packet:
        """Set the Initiator Task Tag to the reserved value (0xFFFFFFFF)
        for PDUs that require a valid ITT."""
        return _set_iscsi_field(packet, "itt", RESERVED_TAG)

    @staticmethod
    def random_itt(packet: Packet) -> Packet:
        """Set the ITT to a random value that doesn't match any outstanding task."""
        return _set_iscsi_field(packet, "itt", random.randint(0x80000000, 0xFFFFFFFE))

    @staticmethod
    def invalid_ttt(packet: Packet) -> Packet:
        """Set Target Transfer Tag to a random invalid value on Data-Out PDUs."""
        return _set_iscsi_field(packet, "ttt", random.randint(1, 0xFFFFFFFE))

    @staticmethod
    def data_length_mismatch(packet: Packet) -> Packet:
        """Make the data segment length field not match the actual data.

        Sets the data_segment_length header field to a value different
        from the actual payload length.
        """
        iscsi_layer = _find_iscsi_layer(packet)
        if iscsi_layer is None:
            return packet

        # Get actual data length
        actual_len = len(bytes(iscsi_layer.payload)) if iscsi_layer.payload else 0
        if actual_len > 0:
            # Set to a mismatched value
            wrong_len = random.choice([
                actual_len + random.randint(1, 1024),  # Too large
                max(1, actual_len - random.randint(1, min(actual_len, 512))),  # Too small
                0,  # Zero when there's data
            ])
        else:
            # Set non-zero length when there's no data
            wrong_len = random.randint(1, 65536)

        return _set_iscsi_field(packet, "data_segment_length", wrong_len)

    @staticmethod
    def login_key_tamper(packet: Packet) -> Packet:
        """Tamper with iSCSI login negotiation key-value pairs.

        Modifies the login request's text data to include:
        - Invalid parameter values
        - Unknown parameter keys
        - Malformed key-value format
        """
        iscsi_layer = _find_iscsi_layer(packet)
        if iscsi_layer is None or not isinstance(iscsi_layer, ISCSI_Login_Request):
            return packet

        # Generate tampered login data
        tampered_entries = random.choice([
            # Invalid parameter values
            [
                "AuthMethod=INVALID_AUTH\x00",
                "MaxRecvDataSegmentLength=99999999999\x00",
                "ErrorRecoveryLevel=255\x00",
            ],
            # Unknown parameters
            [
                "UnknownParam=SomeValue\x00",
                "X-Evil-Param=Attack\x00",
                f"{'A' * 256}={'B' * 256}\x00",
            ],
            # Malformed format
            [
                "NoEqualsSign\x00",
                "=NoKey\x00",
                "Key=Value=Extra=Parts\x00",
                "\x00\x00\x00",
            ],
            # Extremely long values
            [
                f"InitiatorName={'A' * 4096}\x00",
                f"TargetName={'B' * 4096}\x00",
            ],
        ])

        tampered_text = "".join(tampered_entries).encode("utf-8")

        # Replace the payload
        if iscsi_layer.payload:
            iscsi_layer.remove_payload()
        return packet / Raw(load=tampered_text)

    @staticmethod
    def sequence_number_manipulation(packet: Packet) -> Packet:
        """Manipulate CmdSN/ExpStatSN to invalid values.

        Tests how the target handles out-of-window or wrapped sequence numbers.
        """
        manipulation = random.choice([
            ("cmdsn", 0),                      # Zero CmdSN
            ("cmdsn", 0xFFFFFFFF),             # Max CmdSN
            ("cmdsn", random.randint(0, 0xFFFFFFFF)),  # Random CmdSN
            ("expstatsn", 0xFFFFFFFF),         # Max ExpStatSN
            ("expstatsn", random.randint(0, 0xFFFFFFFF)),  # Random
        ])
        return _set_iscsi_field(packet, manipulation[0], manipulation[1])

    @staticmethod
    def invalid_login_stage(packet: Packet) -> Packet:
        """Set invalid login stage combinations (CSG/NSG).

        For example, NSG < CSG, or invalid stage values.
        """
        iscsi_layer = _find_iscsi_layer(packet)
        if iscsi_layer is None or not isinstance(iscsi_layer, ISCSI_Login_Request):
            return packet

        bad_stages = random.choice([
            (3, 0),     # NSG before CSG (backward)
            (3, 3),     # Already in full feature, transit to full feature
            (2, 0),     # Invalid CSG value
            (0, 2),     # Invalid NSG value
        ])
        iscsi_layer.csg = bad_stages[0]
        iscsi_layer.nsg = bad_stages[1]
        iscsi_layer.transit = 1

        return packet

    @staticmethod
    def version_mismatch(packet: Packet) -> Packet:
        """Set incompatible iSCSI version numbers in login request."""
        iscsi_layer = _find_iscsi_layer(packet)
        if iscsi_layer is None or not isinstance(iscsi_layer, ISCSI_Login_Request):
            return packet

        bad_versions = random.choice([
            (0xFF, 0xFF),   # Version max, min both 0xFF
            (0x01, 0x01),   # Unsupported version 1
            (0x00, 0x01),   # Min > Max (illogical)
            (0x7F, 0x7F),   # Large non-standard version
        ])
        iscsi_layer.version_max = bad_versions[0]
        iscsi_layer.version_min = bad_versions[1]

        return packet

    @staticmethod
    def cdb_overflow(packet: Packet) -> Packet:
        """Create a SCSI command with oversized/malformed CDB.

        Tests buffer overflow handling in the CDB processing.
        """
        iscsi_layer = _find_iscsi_layer(packet)
        if iscsi_layer is None or not isinstance(iscsi_layer, ISCSI_SCSI_Command):
            return packet

        # Fill CDB with random bytes (invalid SCSI opcode + random params)
        bad_cdb = bytes(random.randint(0, 255) for _ in range(16))
        iscsi_layer.cdb = bad_cdb

        return packet

    @staticmethod
    def zero_length_pdu(packet: Packet) -> Packet:
        """Create a PDU with zero total AHS length and zero data segment length
        but with actual data payload (header/payload mismatch)."""
        iscsi_layer = _find_iscsi_layer(packet)
        if iscsi_layer is None:
            return packet

        iscsi_layer.total_ahs_length = 0
        iscsi_layer.data_segment_length = 0

        # Append garbage data that won't be accounted for in the header
        return packet / Raw(load=b"\xDE\xAD\xBE\xEF" * 256)


# =============================================================================
# Helper functions
# =============================================================================

def _find_iscsi_layer(packet: Packet) -> Optional[Packet]:
    """Find the iSCSI layer in a packet stack.

    Searches through the packet layers for any iSCSI PDU type.

    Args:
        packet: Scapy packet to search.

    Returns:
        The iSCSI layer, or None if not found.
    """
    iscsi_types = (
        ISCSI_Login_Request,
        ISCSI_SCSI_Command,
        ISCSI_Data_Out,
        ISCSI_NOP_Out,
        ISCSI_Logout_Request,
    )

    layer = packet
    while layer:
        if isinstance(layer, iscsi_types):
            return layer
        layer = layer.payload if hasattr(layer, 'payload') else None

    return None


def _set_iscsi_field(packet: Packet, field_name: str, value: Any) -> Packet:
    """Set a field on the iSCSI layer of a packet.

    Args:
        packet: Scapy packet containing an iSCSI layer.
        field_name: Name of the field to set.
        value: Value to set.

    Returns:
        Modified packet.
    """
    iscsi_layer = _find_iscsi_layer(packet)
    if iscsi_layer is not None and hasattr(iscsi_layer, field_name):
        setattr(iscsi_layer, field_name, value)
    return packet


# Mapping of iSCSI anomaly names to their functions
ISCSI_ANOMALIES = {
    "invalid_opcode": ISCSIAnomalyMixin.invalid_opcode,
    "wrong_direction_opcode": ISCSIAnomalyMixin.wrong_direction_opcode,
    "invalid_itt": ISCSIAnomalyMixin.invalid_itt,
    "random_itt": ISCSIAnomalyMixin.random_itt,
    "invalid_ttt": ISCSIAnomalyMixin.invalid_ttt,
    "data_length_mismatch": ISCSIAnomalyMixin.data_length_mismatch,
    "login_key_tamper": ISCSIAnomalyMixin.login_key_tamper,
    "sequence_number_manipulation": ISCSIAnomalyMixin.sequence_number_manipulation,
    "invalid_login_stage": ISCSIAnomalyMixin.invalid_login_stage,
    "version_mismatch": ISCSIAnomalyMixin.version_mismatch,
    "cdb_overflow": ISCSIAnomalyMixin.cdb_overflow,
    "zero_length_pdu": ISCSIAnomalyMixin.zero_length_pdu,
}
