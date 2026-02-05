"""iSCSI session state machine for managing full protocol interactions.

Implements the iSCSI session lifecycle including login negotiation,
full-feature phase operations, and logout.
"""

from enum import Enum
from typing import Any, Optional

from scapy.packet import Packet

from .builder import ISCSIBuilder
from .constants import (
    LOGIN_STAGE_SECURITY_NEGOTIATION,
    LOGIN_STAGE_OPERATIONAL_NEGOTIATION,
    LOGIN_STAGE_FULL_FEATURE,
    LOGOUT_REASON_CLOSE_SESSION,
    LOGOUT_REASON_CLOSE_CONNECTION,
)
from ...utils.logging import get_logger

logger = get_logger("protocol.iscsi.session")


class ISCSISessionPhase(str, Enum):
    """iSCSI session phases per RFC 7143."""
    IDLE = "idle"
    SECURITY_NEGOTIATION = "security_negotiation"
    OPERATIONAL_NEGOTIATION = "operational_negotiation"
    FULL_FEATURE = "full_feature"
    LOGOUT_PENDING = "logout_pending"
    CLOSED = "closed"
    ERROR = "error"


class ISCSISession:
    """Manages the state machine for an iSCSI session.

    Tracks the current session phase and generates appropriate PDUs
    for each phase of the session lifecycle. Can operate in two modes:

    1. State-tracking mode: Follows proper protocol state transitions
    2. Injection mode: Allows generating any PDU regardless of state
       (for anomaly/fuzz testing)
    """

    def __init__(
        self,
        builder: ISCSIBuilder,
        strict_mode: bool = True,
    ):
        """Initialize iSCSI session.

        Args:
            builder: iSCSI packet builder instance.
            strict_mode: If True, enforces proper state transitions.
                If False, allows any operation in any state (for fuzzing).
        """
        self.builder = builder
        self.strict_mode = strict_mode
        self.phase = ISCSISessionPhase.IDLE
        self._negotiated_params: dict[str, str] = {}

    def _check_phase(self, allowed_phases: set[ISCSISessionPhase]) -> None:
        """Check that the current phase is one of the allowed phases.

        Only enforced if strict_mode is True.

        Raises:
            ISCSISessionError: If not in an allowed phase.
        """
        if self.strict_mode and self.phase not in allowed_phases:
            raise ISCSISessionError(
                f"Operation not allowed in phase '{self.phase.value}'. "
                f"Allowed phases: {', '.join(p.value for p in allowed_phases)}"
            )

    def build_login_security(self) -> Packet:
        """Build a Security Negotiation login request.

        Returns:
            Complete Ether/IP/TCP/iSCSI login request packet.
        """
        self._check_phase({ISCSISessionPhase.IDLE, ISCSISessionPhase.SECURITY_NEGOTIATION})
        self.phase = ISCSISessionPhase.SECURITY_NEGOTIATION
        logger.debug("Building security negotiation login request")
        return self.builder.build_packet("login_request", stage="security", transit=True)

    def build_login_operational(self) -> Packet:
        """Build an Operational Negotiation login request.

        Returns:
            Complete Ether/IP/TCP/iSCSI login request packet.
        """
        self._check_phase({
            ISCSISessionPhase.SECURITY_NEGOTIATION,
            ISCSISessionPhase.OPERATIONAL_NEGOTIATION,
        })
        self.phase = ISCSISessionPhase.OPERATIONAL_NEGOTIATION
        logger.debug("Building operational negotiation login request")
        return self.builder.build_packet("login_request", stage="operational", transit=True)

    def complete_login(self) -> None:
        """Mark login as complete, transitioning to Full Feature phase.

        Call this after receiving a successful login response from the target.
        """
        self._check_phase({
            ISCSISessionPhase.SECURITY_NEGOTIATION,
            ISCSISessionPhase.OPERATIONAL_NEGOTIATION,
        })
        self.phase = ISCSISessionPhase.FULL_FEATURE
        logger.info("iSCSI session entered Full Feature phase")

    def build_scsi_read(
        self,
        lba: int = 0,
        block_count: int = 1,
        lun: int = 0,
    ) -> Packet:
        """Build a SCSI READ command.

        Args:
            lba: Logical Block Address.
            block_count: Number of blocks.
            lun: Logical Unit Number.

        Returns:
            Complete Ether/IP/TCP/iSCSI SCSI Command packet.
        """
        self._check_phase({ISCSISessionPhase.FULL_FEATURE})
        return self.builder.build_packet(
            "scsi_read", lba=lba, block_count=block_count, lun=lun
        )

    def build_scsi_write(
        self,
        lba: int = 0,
        block_count: int = 1,
        data: Optional[bytes] = None,
        lun: int = 0,
    ) -> Packet:
        """Build a SCSI WRITE command.

        Args:
            lba: Logical Block Address.
            block_count: Number of blocks.
            data: Write data (immediate data).
            lun: Logical Unit Number.

        Returns:
            Complete Ether/IP/TCP/iSCSI SCSI Command packet.
        """
        self._check_phase({ISCSISessionPhase.FULL_FEATURE})
        return self.builder.build_packet(
            "scsi_write", lba=lba, block_count=block_count, data=data, lun=lun
        )

    def build_data_out(
        self,
        data: bytes,
        ttt: int = 0xFFFFFFFF,
        datasn: int = 0,
        buffer_offset: int = 0,
        final: bool = True,
    ) -> Packet:
        """Build a SCSI Data-Out PDU.

        Args:
            data: Write data payload.
            ttt: Target Transfer Tag from R2T.
            datasn: Data Sequence Number.
            buffer_offset: Buffer offset.
            final: Whether this is the final data PDU.

        Returns:
            Complete Ether/IP/TCP/iSCSI Data-Out packet.
        """
        self._check_phase({ISCSISessionPhase.FULL_FEATURE})
        return self.builder.build_packet(
            "data_out", data=data, ttt=ttt, datasn=datasn,
            buffer_offset=buffer_offset, final=final,
        )

    def build_nop_out(self) -> Packet:
        """Build a NOP-Out (keepalive) PDU.

        Returns:
            Complete Ether/IP/TCP/iSCSI NOP-Out packet.
        """
        self._check_phase({ISCSISessionPhase.FULL_FEATURE})
        return self.builder.build_packet("nop_out")

    def build_task_management(
        self,
        function: int = 1,
        ref_itt: int = 0xFFFFFFFF,
        lun: int = 0,
    ) -> Packet:
        """Build a Task Management Request PDU.

        Args:
            function: Task management function code.
            ref_itt: Referenced task's ITT.
            lun: Logical Unit Number.

        Returns:
            Complete Ether/IP/TCP/iSCSI Task Management packet.
        """
        self._check_phase({ISCSISessionPhase.FULL_FEATURE})
        return self.builder.build_packet(
            "task_management", function=function, ref_itt=ref_itt, lun=lun
        )

    def build_text_request(self, text_data: Optional[str] = None) -> Packet:
        """Build a Text Request PDU.

        Args:
            text_data: Key-value text data.

        Returns:
            Complete Ether/IP/TCP/iSCSI Text Request packet.
        """
        self._check_phase({ISCSISessionPhase.FULL_FEATURE})
        return self.builder.build_packet("text_request", text_data=text_data)

    def build_logout(
        self,
        reason: int = LOGOUT_REASON_CLOSE_SESSION,
    ) -> Packet:
        """Build a Logout Request PDU.

        Args:
            reason: Logout reason code.

        Returns:
            Complete Ether/IP/TCP/iSCSI Logout Request packet.
        """
        self._check_phase({ISCSISessionPhase.FULL_FEATURE})
        self.phase = ISCSISessionPhase.LOGOUT_PENDING
        return self.builder.build_packet("logout_request", reason=reason)

    def complete_logout(self) -> None:
        """Mark logout as complete."""
        self.phase = ISCSISessionPhase.CLOSED
        logger.info("iSCSI session closed")

    def build_login_sequence(self) -> list[Packet]:
        """Build the complete login sequence (security + operational).

        Returns:
            List of login packets in order.
        """
        packets = []
        packets.append(self.build_login_security())
        # Note: In real usage, you'd wait for a response between these.
        # For testing/fuzzing, we generate both immediately.
        packets.append(self.build_login_operational())
        return packets

    def build_full_session_sequence(
        self,
        operations: Optional[list[dict]] = None,
    ) -> list[Packet]:
        """Build a complete session: login -> operations -> logout.

        Args:
            operations: List of operation dicts with 'type' and params.
                If None, performs a simple read.

        Returns:
            List of packets for the complete session.

        Example:
            >>> session.build_full_session_sequence([
            ...     {'type': 'scsi_read', 'lba': 0, 'block_count': 10},
            ...     {'type': 'scsi_write', 'lba': 100, 'block_count': 1},
            ...     {'type': 'nop_out'},
            ... ])
        """
        # Save strict mode and force for sequence building
        was_strict = self.strict_mode
        self.strict_mode = False
        self.phase = ISCSISessionPhase.IDLE

        packets = []

        try:
            # Login
            packets.extend(self.build_login_sequence())
            self.phase = ISCSISessionPhase.FULL_FEATURE

            # Operations
            if operations is None:
                operations = [{"type": "scsi_read", "lba": 0, "block_count": 1}]

            for op in operations:
                op_type = op.pop("type", "nop_out")
                method_name = f"build_{op_type}"
                method = getattr(self, method_name, None)
                if method:
                    packets.append(method(**op))
                else:
                    logger.warning("Unknown operation type: %s", op_type)

            # Logout
            packets.append(self.build_logout())

        finally:
            self.strict_mode = was_strict

        return packets

    def reset(self) -> None:
        """Reset session state to idle."""
        self.phase = ISCSISessionPhase.IDLE
        self._negotiated_params.clear()
        logger.debug("iSCSI session reset")


class ISCSISessionError(Exception):
    """Raised when an iSCSI session operation is invalid."""
    pass
