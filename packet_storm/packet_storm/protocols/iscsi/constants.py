"""iSCSI protocol constants per RFC 7143.

Defines opcodes, flags, limits, and other constants used in
iSCSI PDU construction and validation.
"""

# =============================================================================
# iSCSI Opcodes (RFC 7143 Section 11.1)
# =============================================================================

# Initiator opcodes (bit 6 = 0)
class InitiatorOpcode:
    NOP_OUT = 0x00
    SCSI_COMMAND = 0x01
    TASK_MANAGEMENT = 0x02
    LOGIN_REQUEST = 0x03
    TEXT_REQUEST = 0x04
    SCSI_DATA_OUT = 0x05
    LOGOUT_REQUEST = 0x06
    SNACK_REQUEST = 0x10

    ALL = {
        NOP_OUT: "NOP-Out",
        SCSI_COMMAND: "SCSI Command",
        TASK_MANAGEMENT: "Task Management",
        LOGIN_REQUEST: "Login Request",
        TEXT_REQUEST: "Text Request",
        SCSI_DATA_OUT: "SCSI Data-Out",
        LOGOUT_REQUEST: "Logout Request",
        SNACK_REQUEST: "SNACK Request",
    }


# Target opcodes (bit 6 = 1)
class TargetOpcode:
    NOP_IN = 0x20
    SCSI_RESPONSE = 0x21
    TASK_MANAGEMENT_RESPONSE = 0x22
    LOGIN_RESPONSE = 0x23
    TEXT_RESPONSE = 0x24
    SCSI_DATA_IN = 0x25
    LOGOUT_RESPONSE = 0x26
    R2T = 0x31
    ASYNC_MESSAGE = 0x32
    REJECT = 0x3F

    ALL = {
        NOP_IN: "NOP-In",
        SCSI_RESPONSE: "SCSI Response",
        TASK_MANAGEMENT_RESPONSE: "Task Management Response",
        LOGIN_RESPONSE: "Login Response",
        TEXT_RESPONSE: "Text Response",
        SCSI_DATA_IN: "SCSI Data-In",
        LOGOUT_RESPONSE: "Logout Response",
        R2T: "R2T",
        ASYNC_MESSAGE: "Async Message",
        REJECT: "Reject",
    }


ALL_OPCODES = {**InitiatorOpcode.ALL, **TargetOpcode.ALL}

# =============================================================================
# PDU Flags
# =============================================================================

# BHS (Basic Header Segment) common flags
BHS_FLAG_IMMEDIATE = 0x40  # Immediate delivery flag
BHS_FLAG_FINAL = 0x80      # Final PDU in sequence

# SCSI Command flags
SCSI_CMD_FLAG_READ = 0x40
SCSI_CMD_FLAG_WRITE = 0x20
SCSI_CMD_ATTR_MASK = 0x07
SCSI_CMD_ATTR_UNTAGGED = 0x00
SCSI_CMD_ATTR_SIMPLE = 0x01
SCSI_CMD_ATTR_ORDERED = 0x02
SCSI_CMD_ATTR_HEAD_OF_QUEUE = 0x03
SCSI_CMD_ATTR_ACA = 0x04

# Login flags
LOGIN_FLAG_TRANSIT = 0x80
LOGIN_FLAG_CONTINUE = 0x40
LOGIN_CSG_MASK = 0x0C
LOGIN_NSG_MASK = 0x03

# Login stages
LOGIN_STAGE_SECURITY_NEGOTIATION = 0
LOGIN_STAGE_OPERATIONAL_NEGOTIATION = 1
LOGIN_STAGE_FULL_FEATURE = 3

# Logout reason codes
LOGOUT_REASON_CLOSE_SESSION = 0
LOGOUT_REASON_CLOSE_CONNECTION = 1
LOGOUT_REASON_RECOVERY = 2

# =============================================================================
# Task Management Function Codes
# =============================================================================

TASK_MGMT_ABORT_TASK = 1
TASK_MGMT_ABORT_TASK_SET = 2
TASK_MGMT_CLEAR_ACA = 3
TASK_MGMT_CLEAR_TASK_SET = 4
TASK_MGMT_LUN_RESET = 5
TASK_MGMT_TARGET_WARM_RESET = 6
TASK_MGMT_TARGET_COLD_RESET = 7
TASK_MGMT_TASK_REASSIGN = 8

# =============================================================================
# Sizes and Limits
# =============================================================================

# Basic Header Segment size (always 48 bytes)
BHS_SIZE = 48

# Default Maximum Receive Data Segment Length
DEFAULT_MAX_RECV_DATA_SEGMENT_LENGTH = 65536

# Maximum CDB length in BHS
BHS_CDB_LENGTH = 16

# iSCSI default port
ISCSI_DEFAULT_PORT = 3260

# Special tag values
RESERVED_TAG = 0xFFFFFFFF  # Reserved ITT/TTT value

# =============================================================================
# SCSI Command Descriptor Block (CDB) opcodes
# =============================================================================

class ScsiOpcode:
    TEST_UNIT_READY = 0x00
    INQUIRY = 0x12
    READ_CAPACITY_10 = 0x25
    READ_10 = 0x28
    WRITE_10 = 0x2A
    READ_16 = 0x88
    WRITE_16 = 0x8A
    READ_CAPACITY_16 = 0x9E
    REPORT_LUNS = 0xA0

    ALL = {
        TEST_UNIT_READY: "TEST UNIT READY",
        INQUIRY: "INQUIRY",
        READ_CAPACITY_10: "READ CAPACITY (10)",
        READ_10: "READ (10)",
        WRITE_10: "WRITE (10)",
        READ_16: "READ (16)",
        WRITE_16: "WRITE (16)",
        READ_CAPACITY_16: "READ CAPACITY (16)",
        REPORT_LUNS: "REPORT LUNS",
    }


# =============================================================================
# Key-Value pairs for login negotiation
# =============================================================================

LOGIN_KEYS = {
    "AuthMethod",
    "HeaderDigest",
    "DataDigest",
    "MaxConnections",
    "TargetName",
    "InitiatorName",
    "TargetAlias",
    "InitiatorAlias",
    "TargetAddress",
    "TargetPortalGroupTag",
    "InitialR2T",
    "ImmediateData",
    "MaxBurstLength",
    "FirstBurstLength",
    "DefaultTime2Wait",
    "DefaultTime2Retain",
    "MaxOutstandingR2T",
    "DataPDUInOrder",
    "DataSequenceInOrder",
    "ErrorRecoveryLevel",
    "SessionType",
    "MaxRecvDataSegmentLength",
}
