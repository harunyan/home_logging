#!/usr/bin/env python3
"""
Interactive calibration tool for HX711 + Load Cell.
Measures tare offset and reference unit (calibration factor),
then automatically updates config.json.
"""

import json
import os
import sys
import time
from hx711 import HX711

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "server_url": "http://192.168.1.129:8080",
        "device_id": "raspi4-feeder-01",
        "device_type": "feeder",
        "mode": "feeder",
        "pin_dout": 6,
        "pin_pd_sck": 5,
        "gain": 128,
        "reference_unit": 357.83,
        "offset": 37524.28,
        "enable_env_iv": True,
        "mock_mode": False
    }


def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    print(f"✅ 設定を保存しました: {CONFIG_FILE}")


def main():
    print("==================================================")
    print("⚖️  HX711 ロードセル キャリブレーション (校正)")
    print("==================================================")

    cfg = load_config()
    dout = cfg.get("pin_dout", 5)
    sck = cfg.get("pin_pd_sck", 6)
    mock = cfg.get("mock_mode", False)

    print(f"GPIO設定: DOUT=BCM{dout}, SCK=BCM{sck} (Mock={mock})")
    hx = HX711(dout_pin=dout, pd_sck_pin=sck, gain=cfg.get("gain", 128), mock=mock)

    try:
        # Step 1: Tare (ゼロ点合わせ)
        print("\n[ステップ 1/2] ゼロ点合わせ (風袋引き)")
        print("測定台（天板・皿）の上に何も乗せず、静止させてください。")
        input("準備ができたら [Enter] キーを押してください...")

        print("ゼロ点を測定中...", end="", flush=True)
        offset = hx.tare(times=20)
        print(f" 完了! (Offset raw: {offset:.1f})")

        # Step 2: Reference Weight (既知の重り測定)
        print("\n[ステップ 2/2] 既知の重りによる係数算出")
        print("重さが分かっている物体（例: 500gのペットボトルや分銅）を台の中央に乗せてください。")
        weight_str = input("乗せた重りの重量(グラム)を入力してください (例: 500): ").strip()
        
        try:
            known_weight = float(weight_str)
            if known_weight <= 0:
                raise ValueError
        except ValueError:
            print("❌ 正しい数値を入力してください。終了します。")
            return

        print("重りを測定中...", end="", flush=True)
        raw_val = hx.read_average(times=20)
        delta_raw = raw_val - offset
        
        if delta_raw == 0:
            print("\n❌ 変化が検知されませんでした。配線やロードセルを確認してください。")
            return

        ref_unit = delta_raw / known_weight
        print(f" 完了!")
        print(f" -> 差分ADC値: {delta_raw:.1f}")
        print(f" -> 算出校正係数 (Reference Unit): {ref_unit:.4f}")

        # Update config
        cfg["offset"] = offset
        cfg["reference_unit"] = ref_unit
        save_config(cfg)

        hx.set_reference_unit(ref_unit)
        hx.set_offset(offset)

        # Step 3: Verification
        print("\n[動作確認テスト] (Ctrl+C で終了)")
        print("リアルタイム重量表示:")
        while True:
            w = hx.get_weight(times=5)
            print(f"\r測定値: {w:8.2f} g  (ADC: {hx.read_raw()})", end="", flush=True)
            time.sleep(0.3)

    except KeyboardInterrupt:
        print("\n\nキャリブレーションを終了しました。")
    finally:
        hx.cleanup()


if __name__ == "__main__":
    main()
