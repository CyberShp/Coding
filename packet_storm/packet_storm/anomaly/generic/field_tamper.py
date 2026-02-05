"""Field tampering anomaly - randomly or specifically modifies packet fields."""

import random
from typing import Any, Optional

from scapy.packet import Packet

from ..base import BaseAnomaly
from ..registry import register_anomaly
from ...utils.logging import get_logger

logger = get_logger("anomaly.field_tamper")


@register_anomaly
class FieldTamperAnomaly(BaseAnomaly):
    """Tampers with specific or random fields in a packet.

    Supports multiple tampering modes:
    - 'random': Replace field with a random value
    - 'zero': Set field to zero
    - 'max': Set field to maximum value
    - 'specific': Set to a user-specified value
    - 'bitflip': Flip random bits in the field
    """

    NAME = "field_tamper"
    DESCRIPTION = "Tamper with packet fields (random, zero, max, bitflip, or specific value)"
    CATEGORY = "generic"
    APPLIES_TO = ["all"]

    def __init__(self, config: dict):
        super().__init__(config)
        self._target_layer = config.get("target_layer", "")
        self._target_field = config.get("target_field", "")
        self._mode = config.get("mode", "random")
        self._specific_value = config.get("value", None)

    def apply(self, packet: Packet) -> Packet:
        """Apply field tampering to the packet.

        If target_field is specified, tampers that field.
        If not, picks a random field from a random layer.
        """
        pkt = self._copy_packet(packet)
        self._applied_count += 1

        if self._target_field:
            # Tamper a specific field
            layer = self._find_layer(pkt, self._target_layer)
            if layer is not None:
                self._tamper_field(layer, self._target_field)
        else:
            # Tamper a random field in a random layer
            layer = self._pick_random_layer(pkt)
            if layer is not None:
                fields = [f.name for f in layer.fields_desc]
                if fields:
                    field_name = random.choice(fields)
                    self._tamper_field(layer, field_name)

        return pkt

    def _tamper_field(self, layer: Packet, field_name: str) -> None:
        """Apply the tampering mode to a specific field."""
        if not hasattr(layer, field_name):
            return

        current_value = getattr(layer, field_name)

        if self._mode == "specific" and self._specific_value is not None:
            new_value = self._specific_value
        elif self._mode == "zero":
            new_value = self._zero_value(current_value)
        elif self._mode == "max":
            new_value = self._max_value(current_value, layer, field_name)
        elif self._mode == "bitflip":
            new_value = self._bitflip_value(current_value)
        else:  # random
            new_value = self._random_value(current_value, layer, field_name)

        try:
            setattr(layer, field_name, new_value)
            logger.debug(
                "Tampered %s.%s: %s -> %s",
                layer.name, field_name, current_value, new_value,
            )
        except Exception as e:
            logger.debug("Failed to tamper %s.%s: %s", layer.name, field_name, e)

    @staticmethod
    def _zero_value(current: Any) -> Any:
        """Return a zero value matching the type of current."""
        if isinstance(current, int):
            return 0
        elif isinstance(current, bytes):
            return b"\x00" * len(current)
        elif isinstance(current, str):
            return ""
        return 0

    @staticmethod
    def _max_value(current: Any, layer: Packet, field_name: str) -> Any:
        """Return a maximum value for the field."""
        if isinstance(current, int):
            # Try to determine max from field descriptor
            for f in layer.fields_desc:
                if f.name == field_name:
                    if hasattr(f, 'sz'):
                        return (1 << (f.sz * 8)) - 1
                    elif hasattr(f, 'size'):
                        return (1 << f.size) - 1
            return 0xFFFFFFFF
        elif isinstance(current, bytes):
            return b"\xFF" * len(current)
        return 0xFFFFFFFF

    @staticmethod
    def _random_value(current: Any, layer: Packet, field_name: str) -> Any:
        """Return a random value for the field."""
        if isinstance(current, int):
            for f in layer.fields_desc:
                if f.name == field_name:
                    if hasattr(f, 'sz'):
                        max_val = (1 << (f.sz * 8)) - 1
                        return random.randint(0, max_val)
                    elif hasattr(f, 'size'):
                        max_val = (1 << f.size) - 1
                        return random.randint(0, max_val)
            return random.randint(0, 0xFFFFFFFF)
        elif isinstance(current, bytes):
            return bytes(random.randint(0, 255) for _ in range(len(current)))
        elif isinstance(current, str):
            return "".join(chr(random.randint(32, 126)) for _ in range(len(current)))
        return random.randint(0, 0xFFFF)

    @staticmethod
    def _bitflip_value(current: Any) -> Any:
        """Flip random bits in the current value."""
        if isinstance(current, int):
            # Flip 1-3 random bits
            for _ in range(random.randint(1, 3)):
                bit_pos = random.randint(0, 31)
                current ^= (1 << bit_pos)
            return current
        elif isinstance(current, bytes):
            data = bytearray(current)
            if data:
                pos = random.randint(0, len(data) - 1)
                data[pos] ^= (1 << random.randint(0, 7))
            return bytes(data)
        return current

    @staticmethod
    def _find_layer(packet: Packet, layer_name: str) -> Optional[Packet]:
        """Find a layer by name in the packet stack."""
        if not layer_name:
            return packet
        layer = packet
        while layer:
            if layer.name.lower().replace(" ", "_") == layer_name.lower().replace(" ", "_"):
                return layer
            if hasattr(layer, 'name') and layer_name.lower() in layer.name.lower():
                return layer
            layer = layer.payload if hasattr(layer, 'payload') and layer.payload else None
        return None

    @staticmethod
    def _pick_random_layer(packet: Packet) -> Optional[Packet]:
        """Pick a random layer from the packet stack."""
        layers = []
        layer = packet
        while layer:
            layers.append(layer)
            layer = layer.payload if hasattr(layer, 'payload') and layer.payload else None
        return random.choice(layers) if layers else None
