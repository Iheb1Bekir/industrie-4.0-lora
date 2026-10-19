"""Transport layer. Two strictly separate modes:

SIMULATION  SimulationTransport: 16-byte payloads arrive as text lines ("... hex=<32 hex chars>") from a file, stdin,
            or a generator. This is NOT LoRa - it is a software stand-in for the radio receive call.
HARDWARE    Sx1276Transport: wraps a real radio driver object (SPI) that implements `receive(timeout)->bytes|None`.
            No SX1276 register driver ships with this project; without one it raises RadioUnavailable.
"""
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable, Optional

HEX_RE = re.compile(r"hex=([0-9A-Fa-f]{2,64})\b")


class RadioUnavailable(RuntimeError):
    """Raised when a real SX1276 transport is requested without a driver."""


@dataclass
class LoRaConfig:
    """Link parameters to configure on BOTH node and gateway radios. Verify against local regulations
    (e.g. EU868 sub-band duty cycle <= 1%); values are project defaults, not legal advice."""
    frequency_hz: int = 868_100_000      # report: 868/915 MHz; 915 MHz for US/AU regions
    bandwidth_hz: int = 125_000          # report: 125 kHz
    spreading_factor: int = 7            # report: SF7-SF12
    coding_rate: str = "4/5"
    sync_word: int = 0x12                # private network (0x34 = LoRaWAN public)
    crc_on: bool = True                  # radio CRC in addition to application CRC16
    explicit_header: bool = True
    tx_power_dbm: int = 14
    # SX1276 <-> Raspberry Pi 4 (BCM numbering): SPI0 MOSI=10 MISO=9 SCK=11, NSS=CE0(8), RESET=25, DIO0=24


class Transport(ABC):
    @abstractmethod
    def receive(self, timeout: float = 1.0) -> Optional[bytes]:
        """Return one raw payload, None on timeout, or raise EOFError when a finite source is exhausted."""


class SimulationTransport(Transport):
    def __init__(self, lines: Iterable[str]):
        self._it = iter(lines)
        self.ignored_lines = 0

    def receive(self, timeout=1.0):
        for line in self._it:
            m = HEX_RE.search(line)
            if m:
                try:
                    return bytes.fromhex(m.group(1))
                except ValueError:
                    return b""  # odd-length hex -> decoder reports truncation
            self.ignored_lines += 1
        raise EOFError


class Sx1276Transport(Transport):
    def __init__(self, driver=None, config: Optional[LoRaConfig] = None):
        if driver is None:
            raise RadioUnavailable("no SX1276 driver supplied; see docs/hardware_deployment.md")
        self.driver, self.config = driver, config or LoRaConfig()
        self.driver.configure(self.config)

    def receive(self, timeout=1.0):
        return self.driver.receive(timeout)
