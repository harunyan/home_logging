"""
HX711 24-Bit Analog-to-Digital Converter Driver for Raspberry Pi.
Supports hardware RPi.GPIO and software mock mode for cross-platform simulation.
"""

import time
import statistics
import random
from typing import Optional

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except (ImportError, RuntimeError):
    GPIO_AVAILABLE = False


class HX711:
    def __init__(self, dout_pin: int = 6, pd_sck_pin: int = 5, gain: int = 64, mock: bool = False):
        self.dout_pin = dout_pin
        self.pd_sck_pin = pd_sck_pin
        self.gain = gain
        self.mock = mock or (not GPIO_AVAILABLE)
        
        self.reference_unit = 1.0  # Calibration coefficient
        self.offset = 0            # Tare offset (raw adc)
        
        if self.gain == 128:
            self._gain_pulses = 1
        elif self.gain == 64:
            self._gain_pulses = 3
        elif self.gain == 32:
            self._gain_pulses = 2
        else:
            self._gain_pulses = 1

        if not self.mock:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.pd_sck_pin, GPIO.OUT)
            GPIO.setup(self.dout_pin, GPIO.IN)
            GPIO.output(self.pd_sck_pin, False)
        else:
            print("[HX711] Running in MOCK (Simulation) mode.")
            self._mock_base_adc = 8400000

    def is_ready(self) -> bool:
        if self.mock:
            return True
        return GPIO.input(self.dout_pin) == 0

    def read_raw(self, timeout_sec: float = 2.0) -> Optional[int]:
        """Reads a single 24-bit raw value from HX711 with timeout handling."""
        if self.mock:
            time.sleep(0.01)
            # Simulated noise around mock base
            return int(self._mock_base_adc + random.gauss(0, 150))

        GPIO.output(self.pd_sck_pin, False)

        # Wait until sensor is ready (DOUT goes LOW)
        start_wait = time.time()
        while GPIO.input(self.dout_pin) == 1:
            if time.time() - start_wait > timeout_sec:
                return None  # Return None on timeout instead of crashing
            time.sleep(0.001)

        raw_data = 0
        for _ in range(24):
            GPIO.output(self.pd_sck_pin, True)
            raw_data = (raw_data << 1) | GPIO.input(self.dout_pin)
            GPIO.output(self.pd_sck_pin, False)

        # Additional pulses to set gain for next reading
        for _ in range(self._gain_pulses):
            GPIO.output(self.pd_sck_pin, True)
            GPIO.output(self.pd_sck_pin, False)

        # Convert 2's complement 24-bit to signed integer
        if raw_data & 0x800000:
            raw_data -= 0x1000000

        return raw_data

    def read_average(self, times: int = 5, timeout_sec: float = 15.0) -> float:
        """Reads multiple raw values, retries on timeout, filters outliers with median."""
        start_time = time.time()
        readings = []
        
        while len(readings) < times and (time.time() - start_time < timeout_sec):
            val = self.read_raw(timeout_sec=2.0)
            if val is not None:
                readings.append(val)
            time.sleep(0.01)

        if not readings:
            raise TimeoutError("HX711 センサーからの応答がありませんでした (配線または他のプロセスとの競合を確認してください)")

        # Use median to eliminate spike noise
        return float(statistics.median(readings))

    def set_reference_unit(self, reference_unit: float):
        """Sets the calibration scaling factor."""
        if reference_unit == 0:
            raise ValueError("Reference unit cannot be zero")
        self.reference_unit = reference_unit

    def set_offset(self, offset: float):
        """Sets the tare raw offset."""
        self.offset = offset

    def tare(self, times: int = 15) -> float:
        """Tares the scale (zeros the current reading)."""
        offset = self.read_average(times)
        self.set_offset(offset)
        return offset

    def get_weight(self, times: int = 5) -> float:
        """Calculates current weight in units (e.g. grams) based on tare and reference_unit."""
        val = self.read_average(times) - self.offset
        return val / self.reference_unit

    def power_down(self):
        """Puts HX711 into low-power sleep mode."""
        if not self.mock:
            GPIO.output(self.pd_sck_pin, False)
            GPIO.output(self.pd_sck_pin, True)
            time.sleep(0.0001)

    def power_up(self):
        """Wakes up HX711 from power down."""
        if not self.mock:
            GPIO.output(self.pd_sck_pin, False)
            time.sleep(0.0001)

    def cleanup(self):
        if not self.mock:
            try:
                GPIO.cleanup()
            except Exception:
                pass
