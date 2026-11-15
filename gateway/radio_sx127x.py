"""Register-level SX1276/77/78/79 LoRa receiver driver for the Raspberry Pi gateway (raw LoRa, not LoRaWAN).

STATUS: HARDWARE PENDING - the register logic is unit-tested against a simulated chip (tests/test_radio_driver.py)
but has never talked to a physical module. SX126x chips use a different command set and are NOT supported here.

The SPI bus is injected (`spi.xfer2(list) -> list`, as provided by `spidev.SpiDev`), so the driver has no import-time
hardware dependency and the web application never touches GPIO. IRQ flags are polled over SPI: DIO0 does not need
to be wired. `reset` is an optional callable that pulses the module's RESET line.
"""
import time
from dataclasses import dataclass

REG_FIFO, REG_OP_MODE, REG_FRF_MSB, REG_PA_CONFIG, REG_LNA = 0x00, 0x01, 0x06, 0x09, 0x0C
REG_FIFO_ADDR_PTR, REG_FIFO_RX_BASE, REG_FIFO_RX_CURRENT, REG_IRQ_FLAGS, REG_RX_NB_BYTES = 0x0D, 0x0F, 0x10, 0x12, 0x13
REG_PKT_SNR, REG_PKT_RSSI, REG_MODEM_CONFIG1, REG_MODEM_CONFIG2, REG_PREAMBLE_MSB = 0x19, 0x1A, 0x1D, 0x1E, 0x20
REG_MODEM_CONFIG3, REG_SYNC_WORD, REG_VERSION = 0x26, 0x39, 0x42
MODE_LORA, MODE_SLEEP, MODE_STDBY, MODE_RX_CONT = 0x80, 0x00, 0x01, 0x05
IRQ_RX_DONE, IRQ_CRC_ERROR = 0x40, 0x20
CHIP_VERSION = 0x12
BW_CODES = {7800: 0, 10400: 1, 15600: 2, 20800: 3, 31250: 4, 41700: 5, 62500: 6, 125000: 7, 250000: 8, 500000: 9}
FXOSC, FSTEP = 32_000_000, 32_000_000 / (1 << 19)


class RadioError(RuntimeError):
    pass


@dataclass
class RadioConfig:
    """Must be IDENTICAL to firmware/…/config.h on every node. frequency_hz has no default on purpose."""
    frequency_hz: int
    bandwidth_hz: int = 125_000
    spreading_factor: int = 7
    coding_rate: int = 5            # 4/5
    sync_word: int = 0x12
    preamble: int = 8
    crc_on: bool = True

    def validate(self):
        if not 137_000_000 <= self.frequency_hz <= 1_020_000_000:
            raise RadioError("frequency_hz outside the SX127x range (137-1020 MHz)")
        if self.bandwidth_hz not in BW_CODES:
            raise RadioError(f"unsupported bandwidth; choose one of {sorted(BW_CODES)}")
        if not 6 <= self.spreading_factor <= 12 or not 5 <= self.coding_rate <= 8:
            raise RadioError("spreading_factor must be 6..12 and coding_rate 5..8")


@dataclass
class Packet:
    payload: bytes
    rssi: float
    snr: float
    crc_ok: bool


class SX127x:
    def __init__(self, spi, config: RadioConfig, reset=None, sleep=time.sleep):
        self.spi, self.cfg, self._reset, self._sleep = spi, config, reset, sleep
        self.packets = self.crc_errors = 0

    # ---- SPI primitives --------------------------------------------------------------------------
    def read(self, reg):
        return self.spi.xfer2([reg & 0x7F, 0x00])[1]

    def write(self, reg, value):
        self.spi.xfer2([reg | 0x80, value & 0xFF])

    def read_fifo(self, n):
        return bytes(self.spi.xfer2([REG_FIFO & 0x7F] + [0x00] * n)[1:])

    # ---- configuration ---------------------------------------------------------------------------
    def begin(self):
        """Reset, verify the chip, configure LoRa mode and start continuous reception. Raises RadioError."""
        self.cfg.validate()
        if self._reset:
            self._reset()
            self._sleep(0.01)
        version = self.read(REG_VERSION)
        if version != CHIP_VERSION:
            raise RadioError(f"no SX127x found on SPI (RegVersion = 0x{version:02X}, expected 0x12): check wiring, CS pin and power")
        c = self.cfg
        self.write(REG_OP_MODE, MODE_LORA | MODE_SLEEP)          # LoRa mode can only be selected in sleep
        self._sleep(0.01)
        frf = int(round(c.frequency_hz / FSTEP))
        self.write(REG_FRF_MSB, (frf >> 16) & 0xFF); self.write(REG_FRF_MSB + 1, (frf >> 8) & 0xFF); self.write(REG_FRF_MSB + 2, frf & 0xFF)
        self.write(REG_FIFO_RX_BASE, 0x00)
        self.write(REG_LNA, 0x23)                                # max LNA gain + boost
        self.write(REG_MODEM_CONFIG1, (BW_CODES[c.bandwidth_hz] << 4) | ((c.coding_rate - 4) << 1))   # explicit header
        self.write(REG_MODEM_CONFIG2, (c.spreading_factor << 4) | (0x04 if c.crc_on else 0x00))
        symbol_ms = (1 << c.spreading_factor) / c.bandwidth_hz * 1000
        self.write(REG_MODEM_CONFIG3, 0x04 | (0x08 if symbol_ms > 16 else 0x00))                       # AGC on, LDRO if needed
        self.write(REG_PREAMBLE_MSB, (c.preamble >> 8) & 0xFF); self.write(REG_PREAMBLE_MSB + 1, c.preamble & 0xFF)
        self.write(REG_SYNC_WORD, c.sync_word)
        self.write(REG_IRQ_FLAGS, 0xFF)
        self.write(REG_OP_MODE, MODE_LORA | MODE_RX_CONT)
        if self.read(REG_OP_MODE) & 0x87 != (MODE_LORA | MODE_RX_CONT):
            raise RadioError("radio did not enter continuous receive mode")
        return self

    def healthy(self):
        """Cheap liveness probe used by the gateway service to detect a hung or disconnected module."""
        try:
            return self.read(REG_VERSION) == CHIP_VERSION and self.read(REG_OP_MODE) & 0x87 == (MODE_LORA | MODE_RX_CONT)
        except Exception:  # noqa: BLE001
            return False

    # ---- reception -------------------------------------------------------------------------------
    def poll(self):
        """Return a Packet if one is waiting, else None. Packets failing the radio CRC are returned with crc_ok=False."""
        flags = self.read(REG_IRQ_FLAGS)
        if not flags & IRQ_RX_DONE:
            return None
        n = self.read(REG_RX_NB_BYTES)
        self.write(REG_FIFO_ADDR_PTR, self.read(REG_FIFO_RX_CURRENT))
        payload = self.read_fifo(n)
        snr_raw = self.read(REG_PKT_SNR)
        snr = (snr_raw - 256 if snr_raw > 127 else snr_raw) / 4.0
        offset = -157 if self.cfg.frequency_hz >= 779_000_000 else -164          # HF / LF port (datasheet 5.5.5)
        rssi = offset + self.read(REG_PKT_RSSI) + (snr if snr < 0 else 0)
        self.write(REG_IRQ_FLAGS, 0xFF)
        crc_ok = not flags & IRQ_CRC_ERROR
        self.packets += 1
        self.crc_errors += 0 if crc_ok else 1
        return Packet(payload, round(rssi, 1), snr, crc_ok)

    def receive(self, timeout=1.0, interval=0.01):
        deadline = time.monotonic() + timeout
        while True:
            p = self.poll()
            if p is not None or time.monotonic() >= deadline:
                return p
            self._sleep(interval)
