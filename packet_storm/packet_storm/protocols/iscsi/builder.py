"""High-level iSCSI packet builder.

Provides a convenient API for constructing complete iSCSI packets
(L2 through L7) with proper sequence numbers, tags, and session state.
"""

import struct
import random
from typing import Any, Optional

from scapy.packet import Packet, Raw

from ..base import BaseProtocolBuilder
from ..fields import build_l2_l4_stack
from .constants import (
    InitiatorOpcode,
    ScsiOpcode,
    ISCSI_DEFAULT_PORT,
    LOGIN_STAGE_SECURITY_NEGOTIATION,
    LOGIN_STAGE_OPERATIONAL_NEGOTIATION,
    LOGIN_STAGE_FULL_FEATURE,
    LOGIN_FLAG_TRANSIT,
    SCSI_CMD_ATTR_SIMPLE,
    SCSI_CMD_FLAG_READ,
    SCSI_CMD_FLAG_WRITE,
    LOGOUT_REASON_CLOSE_SESSION,
)
from .pdu import (
    ISCSI_Login_Request,
    ISCSI_SCSI_Command,
    ISCSI_Data_Out,
    ISCSI_NOP_Out,
    ISCSI_Logout_Request,
    ISCSI_Task_Management,
    ISCSI_Text_Request,
    ISCSI_PDU_TYPES,
)
from ...utils.logging import get_logger

logger = get_logger("protocol.iscsi.builder")


class ISCSIBuilder(BaseProtocolBuilder):
    """Builds complete iSCSI packets with L2-L7 headers.

    Manages sequence numbers (CmdSN, ITT) and constructs proper
    iSCSI PDUs encapsulated in TCP/IP/Ethernet frames.
    """

    PROTOCOL_NAME = "iscsi"

    def __init__(self, network_config: dict, protocol_config: dict):
        super().__init__(network_config, protocol_config)

        # iSCSI session state for proper sequencing
        self._cmdsn: int = 1
        self._expstatsn: int = 0
        self._itt: int = 1
        self._isid: int = random.randint(0, 0xFFFFFF)
        self._tsih: int = 0  # Discovered during login
        self._cid: int = 1

        # Network parameters
        self._target_port = protocol_config.get("target_port", ISCSI_DEFAULT_PORT)
        self._source_port = protocol_config.get("source_port", 0)
        self._initiator_name = protocol_config.get(
            "initiator_name", "iqn.2024-01.com.packetstorm:initiator"
        )
        self._target_name = protocol_config.get(
            "target_name", "iqn.2024-01.com.storage:target"
        )

        # TCP state for proper seq/ack
        self._tcp_seq: int = random.randint(0, 0xFFFFFFFF)
        self._tcp_ack: int = 0

        # Default packet type to build
        self._default_packet_type = "login_request"

    def _next_itt(self) -> int:
        """Get next Initiator Task Tag and increment."""
        itt = self._itt
        self._itt = (self._itt + 1) & 0xFFFFFFFF
        if self._itt == 0:
            self._itt = 1  # Skip 0
        return itt

    def _next_cmdsn(self) -> int:
        """Get next CmdSN and increment."""
        cmdsn = self._cmdsn
        self._cmdsn = (self._cmdsn + 1) & 0xFFFFFFFF
        return cmdsn

    def _advance_tcp_seq(self, payload_len: int) -> None:
        """Advance TCP sequence number after sending data."""
        self._tcp_seq = (self._tcp_seq + payload_len) & 0xFFFFFFFF

    def _build_l2_l4(self, tcp_flags: str = "PA") -> Packet:
        """Build the L2-L4 header stack."""
        return build_l2_l4_stack(
            network_config=self.network_config,
            dst_port=self._target_port,
            src_port=self._source_port,
            transport="tcp",
            tcp_flags=tcp_flags,
            seq=self._tcp_seq,
            ack=self._tcp_ack,
        )

    def build_packet(self, packet_type: Optional[str] = None, **kwargs: Any) -> Packet:
        """Build a complete iSCSI packet (L2-L7).

        Args:
            packet_type: Type of iSCSI PDU to build. Options:
                - 'login_request': Login request PDU
                - 'scsi_command': SCSI command PDU
                - 'scsi_read': SCSI read command
                - 'scsi_write': SCSI write command
                - 'data_out': SCSI Data-Out PDU
                - 'nop_out': NOP-Out (keepalive) PDU
                - 'logout_request': Logout request PDU
                - 'task_management': Task management PDU
                - 'text_request': Text request PDU
            **kwargs: PDU-specific parameters.

        Returns:
            Complete Scapy packet (Ether/IP/TCP/iSCSI).
        """
        pdu_type = packet_type or self._default_packet_type

        builders = {
            "login_request": self._build_login_request,
            "scsi_command": self._build_scsi_command,
            "scsi_read": self._build_scsi_read,
            "scsi_write": self._build_scsi_write,
            "data_out": self._build_data_out,
            "nop_out": self._build_nop_out,
            "logout_request": self._build_logout_request,
            "task_management": self._build_task_management,
            "text_request": self._build_text_request,
        }

        builder_func = builders.get(pdu_type)
        if builder_func is None:
            raise ValueError(
                f"Unknown iSCSI packet type: '{pdu_type}'. "
                f"Available: {list(builders.keys())}"
            )

        iscsi_pdu = builder_func(**kwargs)

        # Build complete L2-L7 packet
        l2_l4 = self._build_l2_l4()
        full_packet = l2_l4 / iscsi_pdu

        # Advance TCP seq
        iscsi_bytes = bytes(iscsi_pdu)
        self._advance_tcp_seq(len(iscsi_bytes))

        return full_packet

    def _build_login_request(
        self,
        stage: str = "security",
        transit: bool = True,
        **kwargs: Any,
    ) -> Packet:
        """Build an iSCSI Login Request PDU with key-value data.

        Args:
            stage: Login stage ('security', 'operational').
            transit: Whether to transit to next stage.
        """
        if stage == "security":
            csg = LOGIN_STAGE_SECURITY_NEGOTIATION
            nsg = LOGIN_STAGE_OPERATIONAL_NEGOTIATION
        elif stage == "operational":
            csg = LOGIN_STAGE_OPERATIONAL_NEGOTIATION
            nsg = LOGIN_STAGE_FULL_FEATURE
        else:
            csg = LOGIN_STAGE_SECURITY_NEGOTIATION
            nsg = LOGIN_STAGE_OPERATIONAL_NEGOTIATION

        # Build login key-value data
        kv_pairs = [
            f"InitiatorName={self._initiator_name}",
            f"TargetName={self._target_name}",
            "SessionType=Normal",
            "AuthMethod=None",
        ]
        if stage == "operational":
            kv_pairs = [
                "HeaderDigest=None",
                "DataDigest=None",
                f"MaxRecvDataSegmentLength={self.protocol_config.get('max_recv_data_segment_length', 65536)}",
                "MaxBurstLength=262144",
                "FirstBurstLength=65536",
                "DefaultTime2Wait=2",
                "DefaultTime2Retain=0",
                "MaxOutstandingR2T=1",
                "MaxConnections=1",
                "ImmediateData=Yes",
                "InitialR2T=Yes",
                "DataPDUInOrder=Yes",
                "DataSequenceInOrder=Yes",
                "ErrorRecoveryLevel=0",
            ]

        data_text = "\x00".join(kv_pairs) + "\x00"
        data_bytes = data_text.encode("utf-8")

        pdu = ISCSI_Login_Request(
            transit=1 if transit else 0,
            csg=csg,
            nsg=nsg,
            isid_a=self._isid,
            tsih=self._tsih,
            itt=self._next_itt(),
            cid=self._cid,
            cmdsn=self._next_cmdsn(),
            expstatsn=self._expstatsn,
        ) / Raw(load=data_bytes)

        return pdu

    def _build_scsi_command(
        self,
        cdb: Optional[bytes] = None,
        lun: int = 0,
        read: bool = False,
        write: bool = False,
        data_length: int = 0,
        **kwargs: Any,
    ) -> Packet:
        """Build a generic SCSI Command PDU.

        Args:
            cdb: 16-byte SCSI CDB. If None, builds TEST UNIT READY.
            lun: Logical Unit Number.
            read: Whether this is a read command.
            write: Whether this is a write command.
            data_length: Expected data transfer length.
        """
        if cdb is None:
            cdb = bytes(16)  # TEST UNIT READY

        lun_bytes = struct.pack("!Q", lun)

        pdu = ISCSI_SCSI_Command(
            read=1 if read else 0,
            write=1 if write else 0,
            attr=SCSI_CMD_ATTR_SIMPLE,
            lun=lun_bytes,
            itt=self._next_itt(),
            expected_data_length=data_length,
            cmdsn=self._next_cmdsn(),
            expstatsn=self._expstatsn,
            cdb=cdb.ljust(16, b"\x00")[:16],
        )

        return pdu

    def _build_scsi_read(
        self,
        lba: int = 0,
        block_count: int = 1,
        block_size: int = 512,
        lun: int = 0,
        **kwargs: Any,
    ) -> Packet:
        """Build a SCSI READ(10) command.

        Args:
            lba: Logical Block Address.
            block_count: Number of blocks to read.
            block_size: Size of each block.
            lun: Logical Unit Number.
        """
        # READ(10) CDB
        cdb = struct.pack(
            "!BBIBHBB",
            ScsiOpcode.READ_10,   # opcode
            0,                     # flags
            lba,                   # LBA
            0,                     # reserved / group
            block_count,           # transfer length
            0,                     # control
            0,                     # padding
            0,                     # padding
        )
        cdb = cdb[:10].ljust(16, b"\x00")

        return self._build_scsi_command(
            cdb=cdb,
            lun=lun,
            read=True,
            data_length=block_count * block_size,
        )

    def _build_scsi_write(
        self,
        lba: int = 0,
        block_count: int = 1,
        block_size: int = 512,
        data: Optional[bytes] = None,
        lun: int = 0,
        **kwargs: Any,
    ) -> Packet:
        """Build a SCSI WRITE(10) command with optional immediate data.

        Args:
            lba: Logical Block Address.
            block_count: Number of blocks to write.
            block_size: Size of each block.
            data: Write data (immediate data). If None, no data sent.
            lun: Logical Unit Number.
        """
        # WRITE(10) CDB
        cdb = struct.pack(
            "!BBIBHBB",
            ScsiOpcode.WRITE_10,  # opcode
            0,                     # flags
            lba,                   # LBA
            0,                     # reserved / group
            block_count,           # transfer length
            0,                     # control
            0,                     # padding
            0,                     # padding
        )
        cdb = cdb[:10].ljust(16, b"\x00")

        pdu = self._build_scsi_command(
            cdb=cdb,
            lun=lun,
            write=True,
            data_length=block_count * block_size,
        )

        if data:
            pdu = pdu / Raw(load=data)

        return pdu

    def _build_data_out(
        self,
        data: bytes = b"\x00" * 512,
        ttt: int = 0xFFFFFFFF,
        datasn: int = 0,
        buffer_offset: int = 0,
        final: bool = True,
        lun: int = 0,
        **kwargs: Any,
    ) -> Packet:
        """Build a SCSI Data-Out PDU.

        Args:
            data: Write data payload.
            ttt: Target Transfer Tag from R2T.
            datasn: Data Sequence Number.
            buffer_offset: Buffer offset for this data.
            final: Whether this is the final data PDU.
            lun: Logical Unit Number.
        """
        lun_bytes = struct.pack("!Q", lun)

        pdu = ISCSI_Data_Out(
            final=1 if final else 0,
            lun=lun_bytes,
            itt=self._itt,  # Same ITT as the command
            ttt=ttt,
            expstatsn=self._expstatsn,
            datasn=datasn,
            buffer_offset=buffer_offset,
        ) / Raw(load=data)

        return pdu

    def _build_nop_out(self, **kwargs: Any) -> Packet:
        """Build a NOP-Out (keepalive/ping) PDU."""
        return ISCSI_NOP_Out(
            itt=self._next_itt(),
            cmdsn=self._next_cmdsn(),
            expstatsn=self._expstatsn,
        )

    def _build_logout_request(
        self,
        reason: int = LOGOUT_REASON_CLOSE_SESSION,
        **kwargs: Any,
    ) -> Packet:
        """Build a Logout Request PDU.

        Args:
            reason: Logout reason code (0=session, 1=connection, 2=recovery).
        """
        return ISCSI_Logout_Request(
            reason_code=reason,
            itt=self._next_itt(),
            cid=self._cid,
            cmdsn=self._next_cmdsn(),
            expstatsn=self._expstatsn,
        )

    def _build_task_management(
        self,
        function: int = 1,  # ABORT TASK
        ref_itt: int = 0xFFFFFFFF,
        lun: int = 0,
        **kwargs: Any,
    ) -> Packet:
        """Build a Task Management Request PDU.

        Args:
            function: Task management function code.
            ref_itt: Referenced task tag (ITT of target task).
            lun: Logical Unit Number.
        """
        lun_bytes = struct.pack("!Q", lun)

        return ISCSI_Task_Management(
            function=function,
            lun=lun_bytes,
            itt=self._next_itt(),
            ref_task_tag=ref_itt,
            cmdsn=self._next_cmdsn(),
            expstatsn=self._expstatsn,
        )

    def _build_text_request(
        self,
        text_data: Optional[str] = None,
        **kwargs: Any,
    ) -> Packet:
        """Build a Text Request PDU.

        Args:
            text_data: Key-value text data. If None, sends SendTargets=All.
        """
        if text_data is None:
            text_data = "SendTargets=All\x00"

        data_bytes = text_data.encode("utf-8")

        return ISCSI_Text_Request(
            itt=self._next_itt(),
            cmdsn=self._next_cmdsn(),
            expstatsn=self._expstatsn,
        ) / Raw(load=data_bytes)

    def list_packet_types(self) -> list[str]:
        """List all supported iSCSI packet types."""
        return [
            "login_request",
            "scsi_command",
            "scsi_read",
            "scsi_write",
            "data_out",
            "nop_out",
            "logout_request",
            "task_management",
            "text_request",
        ]

    def list_fields(self, packet_type: Optional[str] = None) -> dict[str, str]:
        """List fields for an iSCSI packet type."""
        common_fields = {
            "opcode": "iSCSI operation code (0x00-0x3F)",
            "immediate": "Immediate delivery flag",
            "flags": "PDU-specific flags byte",
            "total_ahs_length": "Additional Header Segment length",
            "data_segment_length": "Data segment length in bytes",
            "lun": "Logical Unit Number (8 bytes)",
            "itt": "Initiator Task Tag",
            "cmdsn": "Command Sequence Number",
            "expstatsn": "Expected Status Sequence Number",
        }

        type_specific = {
            "login_request": {
                "transit": "Transit to next login stage",
                "continue_flag": "Continue current login stage",
                "csg": "Current Stage (0=security, 1=operational)",
                "nsg": "Next Stage (1=operational, 3=full-feature)",
                "version_max": "Maximum iSCSI version",
                "version_min": "Minimum iSCSI version",
                "isid_a": "Initiator Session ID (type + OUI)",
                "isid_b": "Initiator Session ID (qualifier)",
                "tsih": "Target Session Identifying Handle",
                "cid": "Connection ID",
            },
            "scsi_command": {
                "read": "Read data flag",
                "write": "Write data flag",
                "attr": "Task attributes (0=untagged, 1=simple, etc.)",
                "expected_data_length": "Expected data transfer length",
                "cdb": "SCSI Command Descriptor Block (16 bytes)",
            },
            "data_out": {
                "final": "Final data PDU flag",
                "ttt": "Target Transfer Tag",
                "datasn": "Data Sequence Number",
                "buffer_offset": "Buffer offset for write data",
            },
        }

        result = dict(common_fields)
        if packet_type and packet_type in type_specific:
            result.update(type_specific[packet_type])
        return result

    def set_tcp_state(self, seq: int, ack: int) -> None:
        """Set TCP sequence/acknowledgment numbers for flow injection.

        Args:
            seq: TCP sequence number.
            ack: TCP acknowledgment number.
        """
        self._tcp_seq = seq
        self._tcp_ack = ack

    def set_session_state(
        self,
        cmdsn: Optional[int] = None,
        expstatsn: Optional[int] = None,
        tsih: Optional[int] = None,
    ) -> None:
        """Set iSCSI session state for flow injection.

        Args:
            cmdsn: Command Sequence Number.
            expstatsn: Expected Status Sequence Number.
            tsih: Target Session Identifying Handle.
        """
        if cmdsn is not None:
            self._cmdsn = cmdsn
        if expstatsn is not None:
            self._expstatsn = expstatsn
        if tsih is not None:
            self._tsih = tsih
