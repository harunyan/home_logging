#!/usr/bin/env python3
"""
M5Stack ENV IV Unit (SHT40 + BMP280) reader module for Raspberry Pi via Grove Base HAT.
Supports I2C communication and graceful fallback to Mock mode on non-Linux / test environments.
"""

import time
from typing import Any, Dict, Optional

try:
    import smbus2  # type: ignore
    HAS_SMBUS = True
except ImportError:
    try:
        import smbus  # type: ignore
        smbus2 = smbus
        HAS_SMBUS = True
    except ImportError:
        HAS_SMBUS = False


class SHT40Reader:
    """Reads temperature and relative humidity from Sensirion SHT40 via I2C (0x44)."""

    I2C_ADDR = 0x44
    CMD_MEASURE_HIGH_PRECISION = 0xFD

    def __init__(self, bus: Optional[Any] = None):
        self.bus = bus

    def read(self) -> Optional[Dict[str, float]]:
        if not self.bus:
            return None
        try:
            # Send high precision measurement command
            self.bus.write_byte(self.I2C_ADDR, self.CMD_MEASURE_HIGH_PRECISION)
            time.sleep(0.015)  # 15ms measurement time

            # Read 6 bytes: [Temp MSB, Temp LSB, CRC, Hum MSB, Hum LSB, CRC]
            data = self.bus.read_i2c_block_data(self.I2C_ADDR, 0, 6)
            raw_temp = (data[0] << 8) | data[1]
            raw_hum = (data[3] << 8) | data[4]

            # Conversion formulas according to SHT40 datasheet
            temp_c = -45.0 + 175.0 * (raw_temp / 65535.0)
            hum_pct = -6.0 + 125.0 * (raw_hum / 65535.0)
            hum_pct = max(0.0, min(100.0, hum_pct))

            return {
                "temperature_c": round(temp_c, 2),
                "humidity_pct": round(hum_pct, 2)
            }
        except Exception:
            return None


class BMP280Reader:
    """Reads atmospheric pressure from Bosch BMP280 via I2C (0x76 or 0x77)."""

    def __init__(self, bus: Optional[Any] = None, addr: int = 0x76):
        self.bus = bus
        self.addr = addr
        self.calib = {}
        self.initialized = False
        if self.bus:
            self._init_sensor()

    def _init_sensor(self):
        try:
            # Check Chip ID (0x58 for BMP280)
            chip_id = self.bus.read_byte_data(self.addr, 0xD0)
            if chip_id != 0x58:
                # Try alternate address 0x77
                if self.addr == 0x76:
                    self.addr = 0x77
                    chip_id = self.bus.read_byte_data(self.addr, 0xD0)

            # Read calibration coefficients (0x88..0xA1)
            b = self.bus.read_i2c_block_data(self.addr, 0x88, 24)
            self.calib['dig_T1'] = b[1] << 8 | b[0]
            self.calib['dig_T2'] = self._to_signed(b[3] << 8 | b[2])
            self.calib['dig_T3'] = self._to_signed(b[5] << 8 | b[4])
            self.calib['dig_P1'] = b[7] << 8 | b[6]
            self.calib['dig_P2'] = self._to_signed(b[9] << 8 | b[8])
            self.calib['dig_P3'] = self._to_signed(b[11] << 8 | b[10])
            self.calib['dig_P4'] = self._to_signed(b[13] << 8 | b[12])
            self.calib['dig_P5'] = self._to_signed(b[15] << 8 | b[14])
            self.calib['dig_P6'] = self._to_signed(b[17] << 8 | b[16])
            self.calib['dig_P7'] = self._to_signed(b[19] << 8 | b[18])
            self.calib['dig_P8'] = self._to_signed(b[21] << 8 | b[20])
            self.calib['dig_P9'] = self._to_signed(b[23] << 8 | b[22])

            # Normal mode, temp oversampling x1, pres oversampling x1
            self.bus.write_byte_data(self.addr, 0xF4, 0x27)
            self.initialized = True
        except Exception:
            self.initialized = False

    @staticmethod
    def _to_signed(val: int) -> int:
        return val - 65536 if val > 32767 else val

    def read_pressure(self) -> Optional[float]:
        if not self.initialized or not self.bus:
            return None
        try:
            data = self.bus.read_i2c_block_data(self.addr, 0xF7, 6)
            raw_p = (data[0] << 12) | (data[1] << 4) | (data[2] >> 4)
            raw_t = (data[3] << 12) | (data[4] << 4) | (data[5] >> 4)

            # Temp compensation to get t_fine
            c = self.calib
            v1 = (raw_t / 16384.0 - c['dig_T1'] / 1024.0) * c['dig_T2']
            v2 = ((raw_t / 131072.0 - c['dig_T1'] / 8192.0) ** 2) * c['dig_T3']
            t_fine = v1 + v2

            # Pressure compensation
            p_v1 = (t_fine / 2.0) - 64000.0
            p_v2 = p_v1 * p_v1 * c['dig_P6'] / 32768.0
            p_v2 = p_v2 + p_v1 * c['dig_P5'] * 2.0
            p_v2 = (p_v2 / 4.0) + (c['dig_P4'] * 65536.0)
            p_v1 = (c['dig_P3'] * p_v1 * p_v1 / 524288.0 + c['dig_P2'] * p_v1) / 524288.0
            p_v1 = (1.0 + p_v1 / 32768.0) * c['dig_P1']
            if p_v1 == 0:
                return None
            p = 1048576.0 - raw_p
            p = (p - (p_v2 / 4096.0)) * 6250.0 / p_v1
            p_v1 = c['dig_P9'] * p * p / 2147483648.0
            p_v2 = p * c['dig_P8'] / 32768.0
            pressure_pa = p + (p_v1 + p_v2 + c['dig_P7']) / 16.0

            return round(pressure_pa / 100.0, 2)  # Convert Pa to hPa
        except Exception:
            return None


class EnvIVSensor:
    """Unified interface for M5Stack ENV IV (SHT40 + BMP280) on Raspberry Pi via Grove HAT."""

    def __init__(self, i2c_bus_num: int = 1, mock: bool = False):
        self.mock = mock or (not HAS_SMBUS)
        self.bus = None
        self.sht40 = None
        self.bmp280 = None

        if not self.mock:
            try:
                self.bus = smbus2.SMBus(i2c_bus_num)
                self.sht40 = SHT40Reader(self.bus)
                self.bmp280 = BMP280Reader(self.bus)
                print(f"🌡️ M5Stack ENV IV initialized on I2C Bus {i2c_bus_num}")
            except Exception as e:
                print(f"⚠️ Failed to init I2C bus {i2c_bus_num} ({e}). Falling back to Mock mode.")
                self.mock = True

    def read_all(self) -> Dict[str, float]:
        """Returns dict with temperature_c, humidity_pct, and pressure_hpa."""
        if self.mock:
            import random
            return {
                "temperature_c": round(24.0 + random.uniform(-0.8, 1.2), 2),
                "humidity_pct": round(50.0 + random.uniform(-3.0, 3.0), 2),
                "pressure_hpa": round(1013.25 + random.uniform(-1.0, 1.0), 2)
            }

        res = {}
        if self.sht40:
            sht_data = self.sht40.read()
            if sht_data:
                res.update(sht_data)

        if self.bmp280:
            pres = self.bmp280.read_pressure()
            if pres is not None:
                res["pressure_hpa"] = pres

        return res
