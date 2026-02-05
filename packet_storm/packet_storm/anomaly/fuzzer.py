"""Protocol-aware stateful fuzzer for storage protocols.

Provides mutation-based and generation-based fuzzing strategies
that understand protocol structure and state machines.
"""

import random
import struct
import copy
from typing import Any, Optional, Iterator

from scapy.packet import Packet, Raw

from .base import BaseAnomaly
from .registry import register_anomaly
from ..utils.logging import get_logger

logger = get_logger("anomaly.fuzzer")


@register_anomaly
class ProtocolFuzzer(BaseAnomaly):
    """Stateful protocol fuzzer with multiple mutation strategies.

    Strategies:
    - 'mutation': Randomly mutate bytes in the serialized packet
    - 'field_walk': Systematically test boundary values for each field
    - 'structure': Modify packet structure (reorder, duplicate, remove layers)
    - 'generation': Generate random protocol-valid-looking packets
    - 'combined': Use all strategies randomly
    """

    NAME = "fuzzer"
    DESCRIPTION = "Protocol-aware fuzzer with mutation, field-walk, and structure strategies"
    CATEGORY = "generic"
    APPLIES_TO = ["all"]

    # Interesting values for integer field fuzzing
    INTERESTING_INTS_8 = [0, 1, 0x7F, 0x80, 0xFE, 0xFF]
    INTERESTING_INTS_16 = [0, 1, 0x7F, 0x80, 0xFF, 0x100, 0x7FFF, 0x8000, 0xFFFE, 0xFFFF]
    INTERESTING_INTS_32 = [
        0, 1, 0x7F, 0x80, 0xFF, 0x100, 0x7FFF, 0x8000, 0xFFFF, 0x10000,
        0x7FFFFFFF, 0x80000000, 0xFFFFFFFE, 0xFFFFFFFF,
    ]

    def __init__(self, config: dict):
        super().__init__(config)
        self._strategy = config.get("strategy", "combined")
        self._mutation_rate = config.get("mutation_rate", 0.05)  # 5% of bytes
        self._max_mutations = config.get("max_mutations", 20)
        self._seed = config.get("seed", None)
        self._iteration = 0

        if self._seed is not None:
            random.seed(self._seed)

    def apply(self, packet: Packet) -> Packet:
        """Apply fuzzing to the packet."""
        self._applied_count += 1
        self._iteration += 1

        if self._strategy == "combined":
            strategy = random.choice(["mutation", "field_walk", "structure"])
        else:
            strategy = self._strategy

        if strategy == "mutation":
            return self._mutate(packet)
        elif strategy == "field_walk":
            return self._field_walk(packet)
        elif strategy == "structure":
            return self._structure_fuzz(packet)
        elif strategy == "generation":
            return self._generate(packet)
        else:
            return self._mutate(packet)

    def _mutate(self, packet: Packet) -> Packet:
        """Byte-level mutation fuzzing.

        Randomly modifies bytes in the serialized packet using various
        mutation operators.
        """
        raw = bytearray(bytes(packet))
        if not raw:
            return packet

        num_mutations = max(1, min(
            self._max_mutations,
            int(len(raw) * self._mutation_rate)
        ))

        for _ in range(num_mutations):
            pos = random.randint(0, len(raw) - 1)
            operator = random.choice([
                "flip",      # Flip random bits
                "replace",   # Replace with random byte
                "insert",    # Insert a byte
                "delete",    # Delete a byte
                "swap",      # Swap with neighbor
                "repeat",    # Repeat byte
                "boundary",  # Set to boundary value
            ])

            if operator == "flip":
                raw[pos] ^= (1 << random.randint(0, 7))
            elif operator == "replace":
                raw[pos] = random.randint(0, 255)
            elif operator == "insert" and len(raw) < 65535:
                raw.insert(pos, random.randint(0, 255))
            elif operator == "delete" and len(raw) > 14:  # Keep at least Ethernet
                del raw[pos]
            elif operator == "swap" and pos < len(raw) - 1:
                raw[pos], raw[pos + 1] = raw[pos + 1], raw[pos]
            elif operator == "repeat":
                count = random.randint(2, 8)
                raw[pos:pos + 1] = bytes([raw[pos]]) * count
            elif operator == "boundary":
                raw[pos] = random.choice([0x00, 0x01, 0x7F, 0x80, 0xFE, 0xFF])

        logger.debug(
            "Mutated %d positions in %d byte packet",
            num_mutations, len(raw),
        )

        from scapy.layers.l2 import Ether
        try:
            return Ether(bytes(raw))
        except Exception:
            return Raw(load=bytes(raw))

    def _field_walk(self, packet: Packet) -> Packet:
        """Systematically test boundary values for each field.

        On each call, tests the next field with the next interesting value.
        """
        pkt = self._copy_packet(packet)

        # Collect all fields from all layers
        all_fields = []
        layer = pkt
        while layer:
            for field in getattr(layer, 'fields_desc', []):
                current = getattr(layer, field.name, None)
                if isinstance(current, int):
                    all_fields.append((layer, field.name, current))
            layer = layer.payload if hasattr(layer, 'payload') and layer.payload else None

        if not all_fields:
            return pkt

        # Pick a field based on iteration count (round-robin)
        target_layer, field_name, current_value = all_fields[self._iteration % len(all_fields)]

        # Pick an interesting value
        if current_value <= 0xFF:
            interesting = self.INTERESTING_INTS_8
        elif current_value <= 0xFFFF:
            interesting = self.INTERESTING_INTS_16
        else:
            interesting = self.INTERESTING_INTS_32

        # Cycle through interesting values
        idx = (self._iteration // len(all_fields)) % len(interesting)
        new_value = interesting[idx]

        setattr(target_layer, field_name, new_value)
        logger.debug(
            "Field walk: %s.%s = %d (was %d)",
            target_layer.name, field_name, new_value, current_value,
        )

        return pkt

    def _structure_fuzz(self, packet: Packet) -> Packet:
        """Modify packet structure by manipulating layers.

        Operations:
        - Duplicate a layer
        - Remove a layer (keeping L2)
        - Reorder layers
        - Inject a random layer
        """
        operation = random.choice([
            "duplicate_payload",
            "truncate_layers",
            "inject_random_data",
            "duplicate_and_corrupt",
        ])

        if operation == "duplicate_payload":
            # Duplicate the payload section
            raw = bytes(packet)
            # Find payload start (after L2+L3+L4 headers, roughly byte 54+)
            split_point = min(54, len(raw) // 2)
            payload = raw[split_point:]
            result = raw + payload  # Append duplicate payload
            from scapy.layers.l2 import Ether
            try:
                return Ether(result)
            except Exception:
                return Raw(load=result)

        elif operation == "truncate_layers":
            # Keep only L2 + random amount of remaining data
            raw = bytes(packet)
            keep = random.randint(14, len(raw))
            from scapy.layers.l2 import Ether
            try:
                return Ether(raw[:keep])
            except Exception:
                return Raw(load=raw[:keep])

        elif operation == "inject_random_data":
            # Inject random data between L4 header and application payload
            pkt = self._copy_packet(packet)
            garbage = bytes(random.randint(0, 255) for _ in range(random.randint(1, 64)))
            return pkt / Raw(load=garbage)

        elif operation == "duplicate_and_corrupt":
            # Duplicate the full packet and corrupt the duplicate
            raw = bytearray(bytes(packet))
            dup = bytearray(raw)
            # Corrupt some bytes in the duplicate
            for _ in range(random.randint(1, 10)):
                if dup:
                    pos = random.randint(0, len(dup) - 1)
                    dup[pos] = random.randint(0, 255)
            result = bytes(raw) + bytes(dup)
            from scapy.layers.l2 import Ether
            try:
                return Ether(result)
            except Exception:
                return Raw(load=result)

        return self._copy_packet(packet)

    def _generate(self, packet: Packet) -> Packet:
        """Generate a random packet inspired by the structure of the input."""
        # Use the input packet as a template but randomize most fields
        pkt = self._copy_packet(packet)

        layer = pkt
        while layer:
            for field in getattr(layer, 'fields_desc', []):
                current = getattr(layer, field.name, None)
                # 50% chance to randomize each field
                if random.random() < 0.5:
                    if isinstance(current, int):
                        max_val = 0xFF
                        if hasattr(field, 'sz'):
                            max_val = (1 << (field.sz * 8)) - 1
                        elif hasattr(field, 'size'):
                            max_val = (1 << field.size) - 1
                        setattr(layer, field.name, random.randint(0, max_val))
                    elif isinstance(current, bytes):
                        setattr(layer, field.name,
                                bytes(random.randint(0, 255) for _ in range(len(current))))
            layer = layer.payload if hasattr(layer, 'payload') and layer.payload else None

        return pkt
