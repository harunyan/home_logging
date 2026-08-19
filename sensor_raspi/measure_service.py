#!/usr/bin/env python3
"""
Continuous measurement and logging daemon for Raspberry Pi.
Monitors cat weight or food bowl level using HX711 and sends signals to WinSV Go receiver.
Includes offline fallback queuing and noise filtering.
"""

import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional
from hx711 import HX711
from env_sensor import EnvIVSensor
from crypto_client import CryptoClient

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")


class WinSVSender:
    """Handles HTTP POST requests to WinSV Go receiver with local offline buffer and automatic encryption."""

    def __init__(self, server_url: str, queue_file: str = "offline_queue.json"):
        self.server_url = server_url.rstrip("/")
        self.endpoint = f"{self.server_url}/api/v1/events"
        self.queue_file = os.path.join(os.path.dirname(__file__), queue_file)
        self.queue: List[Dict[str, Any]] = self._load_queue()
        self.crypto = CryptoClient(self.server_url)

    def _load_queue(self) -> List[Dict[str, Any]]:
        if os.path.exists(self.queue_file):
            try:
                with open(self.queue_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[Sender] Warning loading queue: {e}")
        return []

    def _save_queue(self):
        try:
            with open(self.queue_file, "w", encoding="utf-8") as f:
                json.dump(self.queue, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Sender] Error saving queue: {e}")

    def send_event(self, event_data: Dict[str, Any]) -> bool:
        """Sends an event to WinSV or queues it if network/server is unreachable."""
        self.queue.append(event_data)
        self._save_queue()
        return self.flush_queue()

    def flush_queue(self) -> bool:
        """Attempts to flush queued events to WinSV with automatic encryption."""
        if not self.queue:
            return True

        for attempt in range(2):
            try:
                # Encrypt payload with ephemeral X25519 + AES-256-GCM (no passwords needed)
                post_data = self.crypto.encrypt_data(self.queue)
                payload = json.dumps(post_data).encode("utf-8")

                req = urllib.request.Request(
                    self.endpoint,
                    data=payload,
                    headers={"Content-Type": "application/json", "User-Agent": "Raspi-Cat-Logger"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=4.0) as resp:
                    if resp.status in (200, 201):
                        count = len(self.queue)
                        enc_tag = "🔒 [Encrypted AES-256-GCM]" if (isinstance(post_data, dict) and post_data.get("encrypted")) else "📡 [Plaintext]"
                        print(f"{enc_tag} [WinSV] Sent {count} event(s) successfully.")
                        self.queue.clear()
                        self._save_queue()
                        return True
            except urllib.error.HTTPError as e:
                print(f"⚠️ [WinSV] HTTP {e.code} ({e.reason}) -> Server key may have changed, refreshing public key...")
                self.crypto.invalidate_key()
                self.crypto.fetch_server_public_key()
                if attempt == 0:
                    time.sleep(0.5)
                    continue  # Retry with fresh key immediately
                return False
            except (urllib.error.URLError, TimeoutError, ConnectionRefusedError, OSError) as e:
                print(f"⚠️ [WinSV] Send failed (buffered {len(self.queue)} events): {e}")
                return False

        return False


class ScaleMonitor:
    """Logic for Cat Scale (cat steps on, stabilizes, steps off)."""

    def __init__(self, hx: HX711, sender: WinSVSender, config: Dict[str, Any], env_sensor: Optional[EnvIVSensor] = None):
        self.hx = hx
        self.sender = sender
        self.config = config
        self.env_sensor = env_sensor
        self.threshold = config.get("scale_threshold_g", 500.0)
        self.device_id = config.get("device_id", "raspi-scale-01")
        self.device_type = "scale"

    def run_loop(self):
        print(f"⚖️ Cat Scale Monitor active. Threshold: {self.threshold}g")
        samples: List[float] = []
        cat_present = False
        start_time = None
        last_env_time = time.time()
        env_interval = self.config.get("env_interval_sec", 60)  # default 1 min

        while True:
            try:
                w = self.hx.get_weight(times=3)
                now = time.time()

                # Filter out obvious sensor glitch values for scale
                if w < 0 or w > 25000:
                    print(f"⚠️ [ScaleMonitor] Ignored glitch reading: {w:.1f}g")
                    time.sleep(0.5)
                    continue

                if w >= self.threshold:
                    if not cat_present:
                        print(f"🐾 Cat stepped onto scale! (Initial: {w:.1f}g)")
                        cat_present = True
                        start_time = now
                        samples = [w]
                    else:
                        samples.append(w)
                        if len(samples) > 20:
                            samples.pop(0)

                elif cat_present and w < (self.threshold * 0.7):
                    # Cat stepped off
                    duration = now - start_time
                    cat_present = False

                    if len(samples) >= 5:
                        sorted_samples = sorted(samples)
                        valid_samples = sorted_samples[2:-2] if len(sorted_samples) >= 8 else sorted_samples
                        measured_weight = sum(valid_samples) / len(valid_samples)

                        # Range validation for cat body weight (100g to 20kg)
                        if 100 <= measured_weight <= 20000:
                            print(f"✅ Cat left scale. Weight: {measured_weight:.1f}g (Duration: {duration:.1f}s)")
                            event_payload = {
                                "device_id": self.device_id,
                                "device_type": self.device_type,
                                "event_type": "weight_measured",
                                "weight_g": round(measured_weight, 2),
                                "note": f"測定時間 {duration:.1f}秒 (サンプル数: {len(samples)})",
                                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
                            }
                            if self.env_sensor:
                                event_payload.update(self.env_sensor.read_all())
                            self.sender.send_event(event_payload)
                        else:
                            print(f"⚠️ [ScaleMonitor] Measured weight out of realistic range ({measured_weight:.1f}g), discarded.")
                    else:
                        print("⚠️ Sampling duration too short, discarded.")

                    samples.clear()

                # Periodic environment logging
                if self.env_sensor and (now - last_env_time >= env_interval):
                    env_data = self.env_sensor.read_all()
                    if env_data:
                        print(f"🌡️ [ENV IV] Temp: {env_data.get('temperature_c')}°C | Hum: {env_data.get('humidity_pct')}%")
                        self.sender.send_event({
                            "device_id": self.device_id,
                            "device_type": self.device_type,
                            "event_type": "env_measured",
                            "note": "M5Stack ENV IV 定期計測",
                            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                            **env_data
                        })
                    last_env_time = now

                time.sleep(self.config.get("sample_interval_sec", 0.5))

            except Exception as e:
                print(f"[ScaleMonitor] Error: {e}")
                time.sleep(1.0)


class FeederMonitor:
    """
    Logic for Food Bowl (1kg Load Cell: 0-1000g).
    Steady state (Bowl + Food): ~150g - 300g.
    - 0g - 130g: Bowl removed / cleaning (ignore meal deductions).
    - 130g - 350g: Normal steady state (idle, food level monitoring).
    - 350g - 1000g: Cat leaning/eating on bowl or human handling (suppress level sync, wait for finish).
    - <0g or >1000g: Hardware / ADC glitch (discard).
    """

    def __init__(self, hx: HX711, sender: WinSVSender, config: Dict[str, Any], env_sensor: Optional[EnvIVSensor] = None):
        self.hx = hx
        self.sender = sender
        self.config = config
        self.env_sensor = env_sensor
        self.change_threshold = config.get("feeder_change_threshold_g", 3.0)
        self.device_id = config.get("device_id", "raspi-feeder-01")
        self.device_type = "feeder"

        # Domain knowledge thresholds
        self.loadcell_max_g = config.get("loadcell_max_g", 1000.0)
        self.bowl_min_steady_g = config.get("bowl_min_steady_g", 130.0)  # Empty bowl threshold
        self.bowl_max_steady_g = config.get("bowl_max_steady_g", 350.0)  # Full bowl upper bound

    def run_loop(self):
        print(f"🍽️ Food Bowl Monitor active. LoadCell: 0-{self.loadcell_max_g}g | Steady range: {self.bowl_min_steady_g}-{self.bowl_max_steady_g}g")
        
        print("安定重量を測定中...")
        baseline = self.hx.get_weight(times=10)
        if not (self.bowl_min_steady_g <= baseline <= self.bowl_max_steady_g):
            print(f"⚠️ 測定値 ({baseline:.1f}g) が通常範囲外です。安全基準値 (220g) を仮設定します。")
            baseline = 220.0
        print(f"初期基準残量: {baseline:.1f}g")

        last_ping_time = time.time()
        ping_interval = self.config.get("ping_interval_sec", 60)  # 1分間隔の定期同期
        last_env_time = time.time()
        env_interval = self.config.get("env_interval_sec", 60)    # 1分間隔の環境測定
        is_cat_eating = False

        while True:
            try:
                current = self.hx.get_weight(times=5)
                now = time.time()

                # 1. Glitch rejection (< 0g or > 1000g)
                if current < 0.0 or current > self.loadcell_max_g:
                    print(f"⚠️ [FeederMonitor] 通信ノイズ・外れ値を破棄: {current:.1f}g")
                    time.sleep(0.5)
                    continue

                # 2. Bowl removed state (< 130g)
                if current < self.bowl_min_steady_g:
                    # Bowl is taken off for cleaning or refilling
                    time.sleep(1.0)
                    continue

                # 3. Cat leaning on bowl / Eating in progress (350g - 1000g)
                if current > self.bowl_max_steady_g:
                    if not is_cat_eating:
                        print(f"🐾 [FeederMonitor] 猫が接触・食事中を検知 (荷重: {current:.1f}g)")
                        is_cat_eating = True
                    time.sleep(0.5)
                    continue

                # 4. Steady state (130g - 350g)
                delta = current - baseline

                # Check if meal finished after cat was leaning, or significant steady weight change occurred
                if is_cat_eating or abs(delta) >= self.change_threshold:
                    time.sleep(2.0)
                    stable_val = self.hx.get_weight(times=10)

                    # Ensure the settled weight is within steady range
                    if self.bowl_min_steady_g <= stable_val <= self.bowl_max_steady_g:
                        actual_delta = stable_val - baseline

                        if actual_delta <= -self.change_threshold:
                            eaten_amount = -actual_delta
                            print(f"🐱 Meal finished! Eaten: {eaten_amount:.1f}g (Remaining: {stable_val:.1f}g)")
                            payload = {
                                "device_id": self.device_id,
                                "device_type": self.device_type,
                                "event_type": "meal_finished",
                                "weight_g": round(stable_val, 2),
                                "delta_g": round(actual_delta, 2),
                                "note": f"喫食量: {eaten_amount:.1f}g",
                                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
                            }
                            if self.env_sensor:
                                payload.update(self.env_sensor.read_all())
                            self.sender.send_event(payload)
                            baseline = stable_val

                        elif actual_delta >= self.change_threshold:
                            refill_amount = actual_delta
                            print(f"🥣 Food Refilled! Added: +{refill_amount:.1f}g (Total: {stable_val:.1f}g)")
                            payload = {
                                "device_id": self.device_id,
                                "device_type": self.device_type,
                                "event_type": "refill",
                                "weight_g": round(stable_val, 2),
                                "delta_g": round(actual_delta, 2),
                                "note": f"補充量: +{refill_amount:.1f}g",
                                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
                            }
                            if self.env_sensor:
                                payload.update(self.env_sensor.read_all())
                            self.sender.send_event(payload)
                            baseline = stable_val

                    is_cat_eating = False

                # 1分おきの定期残量同期 (定常安定状態 130-350g の時のみ送信)
                if now - last_ping_time >= ping_interval:
                    if self.bowl_min_steady_g <= current <= self.bowl_max_steady_g:
                        payload = {
                            "device_id": self.device_id,
                            "device_type": self.device_type,
                            "event_type": "food_level",
                            "weight_g": round(current, 2),
                            "note": "1分定期残量同期",
                            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
                        }
                        if self.env_sensor:
                            payload.update(self.env_sensor.read_all())
                        self.sender.send_event(payload)
                        last_env_time = now  # Reset env timer as well since env was piggybacked
                    last_ping_time = now

                # 独立した定期環境温湿度・気圧ロギング (ロードセル状態に関わらず1分おきに確実に送信)
                if self.env_sensor and (now - last_env_time >= env_interval):
                    env_data = self.env_sensor.read_all()
                    if env_data:
                        status_note = "猫接触・食事中" if is_cat_eating else "定期環境計測"
                        self.sender.send_event({
                            "device_id": self.device_id,
                            "device_type": self.device_type,
                            "event_type": "env_measured",
                            "note": status_note,
                            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                            **env_data
                        })
                    last_env_time = now

                time.sleep(self.config.get("sample_interval_sec", 1.0))

            except Exception as e:
                print(f"[FeederMonitor] Error: {e}")
                # Even if HX711 throws error, ensure environmental logging still operates
                now = time.time()
                if self.env_sensor and (now - last_env_time >= env_interval):
                    env_data = self.env_sensor.read_all()
                    if env_data:
                        self.sender.send_event({
                            "device_id": self.device_id,
                            "device_type": self.device_type,
                            "event_type": "env_measured",
                            "note": f"定期環境計測 (ロードセル待機中: {e})",
                            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                            **env_data
                        })
                    last_env_time = now
                time.sleep(1.0)


def main():
    if not os.path.exists(CONFIG_FILE):
        print(f"❌ 設定ファイルが見つかりません: {CONFIG_FILE}")
        print("まずは calibrate.py を実行して校正を行ってください。")
        sys.exit(1)

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    print("==================================================")
    print("🐾 Cat Logging Sensor Daemon (Raspberry Pi)")
    print("==================================================")
    print(f"Device ID : {cfg.get('device_id')}")
    print(f"Mode      : {cfg.get('mode')}")
    print(f"WinSV URL : {cfg.get('server_url')}")
    print("==================================================")

    sender = WinSVSender(
        server_url=cfg.get("server_url", "http://127.0.0.1:8080"),
        queue_file=cfg.get("offline_queue_file", "offline_queue.json")
    )

    hx = HX711(
        dout_pin=cfg.get("pin_dout", 6),
        pd_sck_pin=cfg.get("pin_pd_sck", 5),
        gain=cfg.get("gain", 64),
        mock=cfg.get("mock_mode", False)
    )

    hx.set_reference_unit(cfg.get("reference_unit", 1.0))
    hx.set_offset(cfg.get("offset", 0.0))

    # Initialize M5Stack ENV IV via Grove HAT (I2C)
    env_sensor = None
    if cfg.get("enable_env_iv", True):
        env_sensor = EnvIVSensor(
            i2c_bus_num=cfg.get("i2c_bus", 1),
            mock=cfg.get("mock_mode", False)
        )

    mode = cfg.get("mode", "scale")
    try:
        if mode == "feeder":
            monitor = FeederMonitor(hx, sender, cfg, env_sensor=env_sensor)
            monitor.run_loop()
        else:
            monitor = ScaleMonitor(hx, sender, cfg, env_sensor=env_sensor)
            monitor.run_loop()
    except KeyboardInterrupt:
        print("\n停止中...")
    finally:
        hx.cleanup()
        print("センサーサービスを終了しました。")


if __name__ == "__main__":
    main()

