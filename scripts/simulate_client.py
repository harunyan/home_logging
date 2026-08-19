#!/usr/bin/env python3
"""
Test client simulation tool for Cat Home Logging System.
Sends simulated scale, feeder, and ENV IV (temperature/humidity/pressure) events to the Go receiver.
Useful for testing the server and dashboard UI in a new development environment.
"""

import argparse
import datetime
import json
import random
import sys
import time
import urllib.error
import urllib.request


def send_event(server_url: str, event_data: dict) -> bool:
    endpoint = f"{server_url.rstrip('/')}/api/v1/events"
    payload = json.dumps(event_data).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            return resp.status in (200, 201)
    except Exception as e:
        print(f"❌ Failed to send event to {endpoint}: {e}")
        return False


def simulate_scale(server_url: str, device_id: str = "sim-cat-scale"):
    base_weight = 4300.0 + random.uniform(-100.0, 100.0)
    event = {
        "device_id": device_id,
        "device_type": "scale",
        "event_type": "weight_measured",
        "weight_g": round(base_weight, 1),
        "temperature_c": round(24.0 + random.uniform(-0.5, 0.8), 1),
        "humidity_pct": round(52.0 + random.uniform(-2.0, 3.0), 1),
        "note": "猫が体重計に乗って測定 (シミュレーション)",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
    print(f"🐾 [Scale] 猫の体重測定: {event['weight_g']}g")
    return send_event(server_url, event)


def simulate_feeder_meal(server_url: str, device_id: str = "sim-cat-feeder"):
    eaten = round(random.uniform(8.0, 22.0), 1)
    remaining = round(random.uniform(15.0, 40.0), 1)
    event = {
        "device_id": device_id,
        "device_type": "feeder",
        "event_type": "meal_finished",
        "weight_g": remaining,
        "delta_g": -eaten,
        "temperature_c": round(24.5 + random.uniform(-0.5, 0.5), 1),
        "humidity_pct": round(51.0 + random.uniform(-2.0, 2.0), 1),
        "note": f"食事完了 (喫食量: {eaten}g / 残量: {remaining}g)",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
    print(f"🍽️ [Feeder] 食事完了: -{eaten}g (残量: {remaining}g)")
    return send_event(server_url, event)


def simulate_feeder_refill(server_url: str, device_id: str = "sim-cat-feeder"):
    refill = round(random.uniform(40.0, 80.0), 1)
    total = round(refill + 10.0, 1)
    event = {
        "device_id": device_id,
        "device_type": "feeder",
        "event_type": "refill",
        "weight_g": total,
        "delta_g": refill,
        "note": f"フード補充 (+{refill}g / 総量: {total}g)",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
    print(f"🥣 [Feeder] フード補充: +{refill}g")
    return send_event(server_url, event)


def simulate_env(server_url: str, device_id: str = "sim-env-raspi"):
    temp = round(24.0 + random.uniform(-1.0, 1.5), 1)
    hum = round(52.0 + random.uniform(-3.0, 4.0), 1)
    press = round(1013.25 + random.uniform(-2.0, 2.0), 1)
    event = {
        "device_id": device_id,
        "device_type": "env_sensor",
        "event_type": "env_measured",
        "temperature_c": temp,
        "humidity_pct": hum,
        "pressure_hpa": press,
        "note": "M5Stack ENV IV (Grove I2C)",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
    print(f"🌡️ [ENV IV] 環境計測: {temp}°C / {hum}% / {press}hPa")
    return send_event(server_url, event)


def main():
    parser = argparse.ArgumentParser(description="Cat Home Logging System Simulation Client")
    parser.add_argument("--url", default="http://127.0.0.1:8080", help="WinSV Go server URL (default: http://127.0.0.1:8080)")
    parser.add_argument("--continuous", action="store_true", help="Run continuous random event loop")
    parser.add_argument("--interval", type=float, default=3.0, help="Interval in seconds for continuous mode")
    parser.add_argument("--type", choices=["all", "scale", "meal", "refill", "env"], default="all", help="Specific event to trigger once")
    args = parser.parse_args()

    print("==================================================")
    print("🐾 Cat Logging Simulation Client")
    print(f"Target Server: {args.url}")
    print("==================================================")

    if not args.continuous:
        if args.type == "scale" or args.type == "all":
            simulate_scale(args.url)
        if args.type == "meal" or args.type == "all":
            simulate_feeder_meal(args.url)
        if args.type == "refill" or args.type == "all":
            simulate_feeder_refill(args.url)
        if args.type == "env" or args.type == "all":
            simulate_env(args.url)
        print("✅ 完了しました。Webダッシュボード (http://localhost:8080) をご確認ください。")
        return

    print("🔄 連続シミュレーション開始 (Ctrl+C で停止)...")
    actions = [simulate_scale, simulate_feeder_meal, simulate_env]
    try:
        while True:
            action = random.choice(actions)
            action(args.url)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n停止しました。")


if __name__ == "__main__":
    main()
