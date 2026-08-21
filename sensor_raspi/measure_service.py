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
    Monitors bowl weight changes with session debounce.
    Treats continuous fluctuations during eating as a single meal session,
    calculating the total eaten amount between session start and end.
    """

    def __init__(self, hx: HX711, sender: WinSVSender, config: Dict[str, Any], env_sensor: Optional[EnvIVSensor] = None):
        self.hx = hx
        self.sender = sender
        self.config = config
        self.env_sensor = env_sensor
        self.change_threshold = config.get("feeder_change_threshold_g", 2.0)  # 2.0g以上の減少で食事検知
        self.device_id = config.get("device_id", "raspi4-feeder-01")
        self.device_type = "feeder"
        self.loadcell_max_g = config.get("loadcell_max_g", 1000.0)
        self.settle_duration_sec = config.get("feeder_settle_sec", 12.0)      # 12秒間変動が収まったらセッション終了

    def run_loop(self):
        print(f"🍽️ Food Bowl Monitor active. Change threshold: {self.change_threshold}g (Settle time: {self.settle_duration_sec}s)")
        
        print("安定重量を測定中...")
        baseline = max(0.0, self.hx.get_weight(times=10))
        print(f"初期基準残量: {baseline:.1f}g")

        last_ping_time = time.time()
        ping_interval = self.config.get("ping_interval_sec", 60)  # 1分間隔の定期同期
        last_env_time = time.time()
        env_interval = self.config.get("env_interval_sec", 60)    # 1分間隔の環境測定
        last_drift_time = time.time()

        # 食事/補充セッション管理
        in_session = False
        session_start_weight = baseline
        last_fluctuation_time = time.time()
        last_observed_weight = baseline

        while True:
            try:
                current = self.hx.get_weight(times=3)
                now = time.time()

                # 1. 通信ノイズ・外れ値の破棄 (< -20g or > loadcell_max_g)
                if current < -20.0 or current > self.loadcell_max_g:
                    print(f"⚠️ [FeederMonitor] 通信ノイズ・外れ値を破棄: {current:.1f}g")
                    time.sleep(1.0)
                    continue

                normalized_current = max(0.0, current)
                delta_from_baseline = normalized_current - baseline

                # 2. 食事・補充セッションの開始判定
                if not in_session:
                    if abs(delta_from_baseline) >= self.change_threshold:
                        in_session = True
                        session_start_weight = baseline
                        last_fluctuation_time = now
                        last_observed_weight = normalized_current
                        print(f"🐾 [食事/補充セッション開始] 開始前残量: {session_start_weight:.1f}g (現在値: {normalized_current:.1f}g)")
                    else:
                        # セッション外で微小な温度ドリフトがあればゆっくり追従 (5分ごと)
                        if now - last_drift_time >= 300:
                            if abs(delta_from_baseline) < 1.0:
                                baseline = normalized_current
                            last_drift_time = now

                else:
                    # 3. セッション継続中 (猫が食事中または作業中)
                    # 重量に有意な動きがあれば変動時刻を更新
                    if abs(normalized_current - last_observed_weight) >= 1.0:
                        last_fluctuation_time = now
                        last_observed_weight = normalized_current

                    # 変動が収まってから settle_duration_sec (12秒) 経過したか？
                    stable_elapsed = now - last_fluctuation_time
                    if stable_elapsed >= self.settle_duration_sec:
                        # 完全に安定した！高精度サンプリングで最終重量を確定
                        final_weight = max(0.0, self.hx.get_weight(times=10))
                        total_delta = final_weight - session_start_weight

                        print(f"🏁 [セッション終了] 開始: {session_start_weight:.1f}g ➜ 終了: {final_weight:.1f}g (総差分: {total_delta:+.1f}g)")

                        if total_delta <= -self.change_threshold:
                            # 猫の食事が完了！ (最初と最後の差分で1回だけ送信)
                            eaten_amount = -total_delta
                            print(f"🐱 【食事完了】 喫食量: {eaten_amount:.1f}g (残量: {final_weight:.1f}g)")
                            payload = {
                                "device_id": self.device_id,
                                "device_type": self.device_type,
                                "event_type": "meal_finished",
                                "weight_g": round(final_weight, 2),
                                "delta_g": round(total_delta, 2),
                                "note": f"猫の食事検知 (喫食量: {eaten_amount:.1f}g)",
                                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
                            }
                            if self.env_sensor:
                                payload.update(self.env_sensor.read_all())
                            self.sender.send_event(payload)

                        elif total_delta >= 15.0:
                            # フード補充が完了！ (1回だけ送信)
                            refill_amount = total_delta
                            print(f"🥣 【フード補充】 補充量: +{refill_amount:.1f}g (合計: {final_weight:.1f}g)")
                            payload = {
                                "device_id": self.device_id,
                                "device_type": self.device_type,
                                "event_type": "refill",
                                "weight_g": round(final_weight, 2),
                                "delta_g": round(total_delta, 2),
                                "note": f"フード補充 (補充量: +{refill_amount:.1f}g)",
                                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
                            }
                            if self.env_sensor:
                                payload.update(self.env_sensor.read_all())
                            self.sender.send_event(payload)

                        else:
                            print(f"ℹ️ 変動差分が微小({total_delta:+.1f}g)のため、イベント送信をスキップしました。")

                        # ベースラインを最終重量に更新してセッション終了
                        baseline = final_weight
                        in_session = False
                        last_ping_time = now
                        last_drift_time = now

                # 4. 定期残量同期 (常時1分間隔で送信)
                if now - last_ping_time >= ping_interval:
                    status_note = "食事中同期" if in_session else "1分定期残量同期"
                    payload = {
                        "device_id": self.device_id,
                        "device_type": self.device_type,
                        "event_type": "food_level",
                        "weight_g": round(normalized_current, 2),
                        "note": status_note,
                        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
                    }
                    if self.env_sensor:
                        payload.update(self.env_sensor.read_all())
                    self.sender.send_event(payload)
                    last_ping_time = now
                    last_env_time = now

                # 5. 独立した定期環境温湿度・気圧ロギング (常時1分間隔)
                if self.env_sensor and (now - last_env_time >= env_interval):
                    env_data = self.env_sensor.read_all()
                    if env_data:
                        status_note = "猫食事中" if in_session else "定期環境計測"
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


class EnvOnlyMonitor:
    """
    Dedicated monitor for standalone ENV IV sensors (e.g. Raspberry Pi Zero + Grove HAT).
    No HX711 loadcell is initialized or required.
    """

    def __init__(self, sender: WinSVSender, config: Dict[str, Any], env_sensor: EnvIVSensor):
        self.sender = sender
        self.config = config
        self.env_sensor = env_sensor
        self.device_id = config.get("device_id", "raspizero-env-01")
        self.device_type = config.get("device_type", "sensor")
        self.interval_sec = config.get("env_interval_sec", 60)

    def run_loop(self):
        print(f"🌡️ [EnvOnlyMonitor] Started for device: {self.device_id} (Interval: {self.interval_sec}s)")
        print(f"📡 WinSV Target: {self.sender.server_url} (Encrypted)")

        while True:
            try:
                env_data = self.env_sensor.read_all()
                if env_data:
                    temp = env_data.get("temperature_c")
                    hum = env_data.get("humidity_pct")
                    press = env_data.get("pressure_hpa")
                    temp_str = f"{temp:.1f}°C" if temp is not None else "--.-°C"
                    hum_str = f"{hum:.1f}%" if hum is not None else "--.-%"
                    press_str = f"{press:.1f} hPa" if press is not None else "--.- hPa"
                    print(f"🌡️ [{self.device_id}] 室温: {temp_str} | 湿度: {hum_str} | 気圧: {press_str}")

                    payload = {
                        "device_id": self.device_id,
                        "device_type": self.device_type,
                        "event_type": "env_measured",
                        "note": self.config.get("note", "Raspberry Pi Zero ENV IV 定期計測"),
                        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        **env_data
                    }
                    self.sender.send_event(payload)

                time.sleep(self.interval_sec)

            except Exception as e:
                print(f"⚠️ [EnvOnlyMonitor] Error: {e}")
                time.sleep(5.0)


def load_config() -> Dict[str, Any]:
    default_offset = 37524.28
    existing_tare_file = "/home/morimoto/www/adc_0g_hx711.txt"
    if os.path.exists(existing_tare_file):
        try:
            with open(existing_tare_file, "r") as f:
                default_offset = float(f.read().strip())
                print(f"📄 既存のゼロ点ファイル ({existing_tare_file}) からオフセットを読み込みました: {default_offset}")
        except Exception:
            pass

    default_config = {
        "server_url": "http://192.168.1.129:8080",
        "device_id": "raspi4-feeder-01",
        "device_type": "feeder",
        "mode": "feeder",
        "pin_dout": 6,
        "pin_pd_sck": 5,
        "gain": 128,
        "reference_unit": 357.83,
        "offset": default_offset,
        "enable_env_iv": True,
        "i2c_bus": 1,
        "mock_mode": False
    }

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                default_config.update(loaded)
        except Exception as e:
            print(f"⚠️ config.json 読み込みエラー: {e}")

    return default_config


def main():
    cfg = load_config()
    mode = cfg.get("mode", "feeder")

    print("==================================================")
    print("🐾 Cat Logging Sensor Daemon (Raspberry Pi)")
    print("==================================================")
    print(f"Device ID : {cfg.get('device_id')}")
    print(f"Mode      : {mode}")
    print(f"WinSV URL : {cfg.get('server_url')}")
    print(f"ENV IV    : {'Enabled' if cfg.get('enable_env_iv', True) else 'Disabled'}")
    if mode != "env_only" and mode != "sensor":
        print(f"Gain      : {cfg.get('gain', 128)}")
        print(f"Ref Unit  : {cfg.get('reference_unit')}")
        print(f"Offset    : {cfg.get('offset')}")
    print("==================================================")

    sender = WinSVSender(
        server_url=cfg.get("server_url", "http://127.0.0.1:8080"),
        queue_file=cfg.get("offline_queue_file", "offline_queue.json")
    )

    # Initialize M5Stack ENV IV via Grove HAT (I2C)
    env_sensor = None
    if cfg.get("enable_env_iv", True):
        env_sensor = EnvIVSensor(
            i2c_bus_num=cfg.get("i2c_bus", 1),
            mock=cfg.get("mock_mode", False)
        )

    # 1. Standalone Environmental Sensor Mode (Raspberry Pi Zero)
    if mode in ("env_only", "sensor", "env"):
        if not env_sensor:
            print("❌ エラー: ENV IV センサーが無効または初期化できませんでした。")
            return
        monitor = EnvOnlyMonitor(sender, cfg, env_sensor)
        try:
            monitor.run_loop()
        except KeyboardInterrupt:
            print("\n停止中...")
        return

    # 2. Scale / Feeder Load Cell Modes (Raspberry Pi 4 / 3)
    hx = HX711(
        dout_pin=cfg.get("pin_dout", 6),
        pd_sck_pin=cfg.get("pin_pd_sck", 5),
        gain=cfg.get("gain", 128),
        mock=cfg.get("mock_mode", False)
    )

    hx.set_reference_unit(cfg.get("reference_unit", 1.0))
    hx.set_offset(cfg.get("offset", 0.0))

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

