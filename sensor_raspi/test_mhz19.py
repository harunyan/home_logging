#!/usr/bin/env python3
import os
import sys
import time

print("=" * 50)
print("🔍 MH-Z19 Diagnostic Tool")
print("=" * 50)
print(f"Current User: {os.getlogin() if hasattr(os, 'getlogin') else os.getenv('USER')}")

ports = ["/dev/serial0", "/dev/ttyAMA0", "/dev/ttyS0", "/dev/ttyUSB0"]
print("\n1. Checking port existence and permissions:")
for p in ports:
    if os.path.exists(p):
        try:
            st = os.stat(p)
            readable = os.access(p, os.R_OK)
            writable = os.access(p, os.W_OK)
            print(f"  ✅ {p} exists (Readable: {readable}, Writable: {writable})")
        except Exception as e:
            print(f"  ⚠️ {p} exists but stat error: {e}")
    else:
        print(f"  ❌ {p} does NOT exist")

print("\n2. Testing mh_z19 library:")
try:
    import mh_z19
    for i in range(1, 6):
        try:
            res = mh_z19.read()
            print(f"  Attempt {i}: mh_z19.read() -> {res}")
            if res and "co2" in res:
                print(f"  🎉 SUCCESS! CO2: {res['co2']} ppm")
                break
        except Exception as e:
            print(f"  Attempt {i}: Error -> {type(e).__name__}: {e}")
        time.sleep(1)
except ImportError:
    print("  ❌ mh_z19 library not installed")

print("\n3. Testing direct PySerial query:")
try:
    import serial
    for p in ports:
        if not os.path.exists(p):
            continue
        try:
            print(f"  Testing {p}...")
            ser = serial.Serial(p, 9600, timeout=2.0)
            ser.reset_input_buffer()
            cmd = b"\xff\x01\x86\x00\x00\x00\x00\x00\x79"
            ser.write(cmd)
            time.sleep(0.1)
            resp = ser.read(9)
            print(f"    Response from {p}: {list(resp)} (len={len(resp)})")
            if len(resp) == 9 and resp[0] == 0xff and resp[1] == 0x86:
                csum = (0xff - (sum(resp[1:8]) % 256) + 1) & 0xff
                co2 = (resp[2] << 8) | resp[3]
                print(f"    🎉 SUCCESS on {p}! CO2: {co2} ppm (Checksum valid: {csum == resp[8]})")
                ser.close()
                break
            ser.close()
        except Exception as e:
            print(f"    Error on {p}: {type(e).__name__}: {e}")
except ImportError:
    print("  ❌ pyserial not installed")
print("=" * 50)
