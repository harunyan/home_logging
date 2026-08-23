#!/usr/bin/env python3
import time
import sys

print("==================================================")
print("🔍 I2C Environmental Sensor Diagnostic Tool")
print("==================================================")

try:
    import smbus2
except ImportError:
    try:
        import smbus as smbus2
    except ImportError:
        print("❌ smbus2 が見つかりません: sudo apt install -y python3-smbus2")
        sys.exit(1)

try:
    bus = smbus2.SMBus(1)
    print("✅ I2C Bus 1 opened successfully.")
except Exception as e:
    print(f"❌ Failed to open I2C Bus 1: {e}")
    sys.exit(1)

# 1. Test SHT40 (0x44)
print("\n--- 1. SHT40 (Temp/Humidity) at 0x44 ---")
try:
    bus.write_byte(0x44, 0xFD)
    time.sleep(0.02)
    data = bus.read_i2c_block_data(0x44, 0, 6)
    raw_t = (data[0] << 8) | data[1]
    raw_h = (data[3] << 8) | data[4]
    t = -45.0 + 175.0 * (raw_t / 65535.0)
    h = -6.0 + 125.0 * (raw_h / 65535.0)
    h = max(0.0, min(100.0, h))
    print(f"  🎉 SHT40 OK: 温度 = {t:.2f} °C, 湿度 = {h:.2f} %")
except Exception as e:
    print(f"  ❌ SHT40 読み取りエラー: {e}")

# 2. Test BMP280 / BME280 / Pressure Sensor (0x76 / 0x77)
print("\n--- 2. Pressure Sensor at 0x76 / 0x77 ---")
for addr in [0x76, 0x77]:
    print(f"Checking address 0x{addr:02X}...")
    try:
        chip_id = bus.read_byte_data(addr, 0xD0)
        print(f"  ✅ Address 0x{addr:02X} responded! Chip ID: 0x{chip_id:02X}")
        if chip_id == 0x58:
            print("    -> Detected: Bosch BMP280")
        elif chip_id == 0x60:
            print("    -> Detected: Bosch BME280")
        elif chip_id in (0x56, 0x57):
            print("    -> Detected: Bosch BMP280 (Sample/Alternative ID)")
        else:
            print(f"    -> Unknown Chip ID: 0x{chip_id:02X}")

        # Read calibration
        b = bus.read_i2c_block_data(addr, 0x88, 24)
        def to_s(val): return val - 65536 if val > 32767 else val
        c = {}
        c['dig_T1'] = b[1] << 8 | b[0]
        c['dig_T2'] = to_s(b[3] << 8 | b[2])
        c['dig_T3'] = to_s(b[5] << 8 | b[4])
        c['dig_P1'] = b[7] << 8 | b[6]
        c['dig_P2'] = to_s(b[9] << 8 | b[8])
        c['dig_P3'] = to_s(b[11] << 8 | b[10])
        c['dig_P4'] = to_s(b[13] << 8 | b[12])
        c['dig_P5'] = to_s(b[15] << 8 | b[14])
        c['dig_P6'] = to_s(b[17] << 8 | b[16])
        c['dig_P7'] = to_s(b[19] << 8 | b[18])
        c['dig_P8'] = to_s(b[21] << 8 | b[20])
        c['dig_P9'] = to_s(b[23] << 8 | b[22])

        # Write config: Normal mode, osrs_t=x1, osrs_p=x1
        bus.write_byte_data(addr, 0xF4, 0x27)
        time.sleep(0.05)

        # Read 6 bytes of pressure + temperature
        data = bus.read_i2c_block_data(addr, 0xF7, 6)
        raw_p = (data[0] << 12) | (data[1] << 4) | (data[2] >> 4)
        raw_t = (data[3] << 12) | (data[4] << 4) | (data[5] >> 4)
        print(f"  Raw sensor readings -> Raw_P: {raw_p}, Raw_T: {raw_t}")

        # Compute compensated pressure
        v1 = (raw_t / 16384.0 - c['dig_T1'] / 1024.0) * c['dig_T2']
        v2 = ((raw_t / 131072.0 - c['dig_T1'] / 8192.0) ** 2) * c['dig_T3']
        t_fine = v1 + v2
        temp_c = t_fine / 5120.0

        p_v1 = (t_fine / 2.0) - 64000.0
        p_v2 = p_v1 * p_v1 * c['dig_P6'] / 32768.0
        p_v2 = p_v2 + p_v1 * c['dig_P5'] * 2.0
        p_v2 = (p_v2 / 4.0) + (c['dig_P4'] * 65536.0)
        p_v1 = (c['dig_P3'] * p_v1 * p_v1 / 524288.0 + c['dig_P2'] * p_v1) / 524288.0
        p_v1 = (1.0 + p_v1 / 32768.0) * c['dig_P1']
        
        if p_v1 != 0:
            p = 1048576.0 - raw_p
            p = (p - (p_v2 / 4096.0)) * 6250.0 / p_v1
            p_v1 = c['dig_P9'] * p * p / 2147483648.0
            p_v2 = p * c['dig_P8'] / 32768.0
            pressure_hpa = (p + (p_v1 + p_v2 + c['dig_P7']) / 16.0) / 100.0
            print(f"  🎉 SUCCESS! 計算結果 -> 気圧: {pressure_hpa:.2f} hPa (内部温度: {temp_c:.2f} °C)")
        else:
            print("  ⚠️ 計算エラー: p_v1 is 0")
    except Exception as e:
        print(f"  ❌ Address 0x{addr:02X} 読み取り失敗: {e}")

print("==================================================")
