#!/usr/bin/env python3
"""
1-Shot Test Script for Raspberry Pi Sensors (HX711 & ENV IV) and WinSV Server Communication.
Reads sensors once, prints formatted results, and sends a test payload to the server.
"""

import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict

# UTF-8 出力対策 (Windows cp932 等での絵文字エラー回避)
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from hx711 import HX711
from env_sensor import EnvIVSensor

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")


def load_config() -> Dict[str, Any]:
    default_config = {
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
        "i2c_bus": 1,
        "mock_mode": False
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                default_config.update(loaded)
                print(f"📖 config.json を読み込みました ({CONFIG_FILE})")
        except Exception as e:
            print(f"⚠️ config.json 読み込みエラー (デフォルト値を使用): {e}")
    else:
        print(f"ℹ️ config.json が見つかりません。デフォルト設定で動作します。")
    return default_config


def main():
    print("=" * 60)
    print("🐾 センサー＆通信 1-Shot 動作確認テスト")
    print("=" * 60)

    config = load_config()
    server_url = config.get("server_url", "http://192.168.1.129:8080").rstrip("/")
    device_id = config.get("device_id", "raspi4-cat-scale")

    # 1. HX711 ロードセル読み取り
    print("\n[1/3] ⚖️ HX711 ロードセルの測定中...")
    hx = HX711(
        dout_pin=config.get("pin_dout", 6),
        pd_sck_pin=config.get("pin_pd_sck", 5),
        gain=config.get("gain", 128),
        mock=config.get("mock_mode", False)
    )
    hx.set_reference_unit(config.get("reference_unit", 357.83))
    hx.set_offset(config.get("offset", 0.0))

    try:
        raw_val = hx.read_average(times=5)
        weight_g = hx.get_weight(times=5)
        print(f"  ├─ DT ピン: GPIO {config.get('pin_dout')}, SCK ピン: GPIO {config.get('pin_pd_sck')}")
        print(f"  ├─ Raw ADC値 : {raw_val:,.1f}")
        print(f"  ├─ Offset    : {config.get('offset'):,.1f}")
        print(f"  ├─ Ref Unit  : {config.get('reference_unit'):,.2f}")
        print(f"  └─ 🎯 計測重量: {weight_g:7.2f} g")
    except Exception as e:
        print(f"  └─ ❌ HX711 読み取り失敗: {e}")
        raw_val = None
        weight_g = None
    finally:
        hx.cleanup()

    # 2. ENV IV (SHT40 + BMP280) 読み取り
    print("\n[2/3] 🌡️ ENV IV 環境センサーの測定中...")
    env_data = {}
    if config.get("enable_env_iv", True):
        env_sensor = EnvIVSensor(
            i2c_bus_num=config.get("i2c_bus", 1),
            mock=config.get("mock_mode", False)
        )
        try:
            env_data = env_sensor.read_all()
            if env_data:
                print(f"  ├─ 気温 : {env_data.get('temperature_c', 'N/A')} °C")
                print(f"  ├─ 湿度 : {env_data.get('humidity_pct', 'N/A')} %")
                print(f"  └─ 気圧 : {env_data.get('pressure_hpa', 'N/A')} hPa")
            else:
                print("  └─ ⚠️ ENV IV データが取得できませんでした (I2C接続を確認してください)")
        except Exception as e:
            print(f"  └─ ❌ ENV IV 読み取り失敗: {e}")
    else:
        print("  └─ (enable_env_iv が false のためスキップ)")

    # 3. サーバー送信テスト
    print(f"\n[3/3] 📡 サーバー送信テスト ➜ {server_url}")
    
    # 3-1. ヘルスチェック
    try:
        health_url = f"{server_url}/health"
        req = urllib.request.Request(health_url, headers={"User-Agent": "Raspi-1Shot-Test"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            body = resp.read().decode("utf-8")
            print(f"  ├─ 疎通確認 (/health): ✅ 成功 (HTTP {resp.status}) ➜ {body}")
    except Exception as e:
        print(f"  ├─ 疎通確認 (/health): ❌ 接続できませんでした ➜ {e}")
        print(f"  │  (Windows側で home_logging_server.exe が起動しているか、IP/ポート/ファイアウォールを確認してください)")

    # 3-2. テストイベント送信
    dev_type = config.get("device_type", "feeder")
    event_type = "weight_measured" if dev_type == "scale" else "food_level"
    note_text = "1-Shot テスト測定 (体重計)" if dev_type == "scale" else "1-Shot テスト測定 (給餌器/餌皿)"

    payload = [{
        "device_id": device_id,
        "device_type": dev_type,
        "event_type": event_type,
        "weight_g": round(weight_g, 2) if weight_g is not None else 0.0,
        "raw_value": int(raw_val) if raw_val is not None else 0,
        "note": note_text,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        **env_data
    }]

    try:
        event_url = f"{server_url}/api/v1/events"
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            event_url,
            data=data_bytes,
            headers={"Content-Type": "application/json", "User-Agent": "Raspi-1Shot-Test"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            resp_body = resp.read().decode("utf-8")
            print(f"  └─ イベント送信 (/api/v1/events): ✅ 成功 (HTTP {resp.status}) ➜ {resp_body}")
    except Exception as e:
        print(f"  └─ イベント送信 (/api/v1/events): ❌ 送信失敗 ➜ {e}")

    print("\n" + "=" * 60)
    print("🏁 1-Shot 動作確認が完了しました。")
    print("=" * 60)


if __name__ == "__main__":
    main()
