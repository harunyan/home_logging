# Raspberry Pi 猫餌ログ・猫体重計・環境温湿度 センサーモジュール

Raspberry Pi上でHX711 24bit ADコンバータとロードセルを制御して猫の体重・食事量を測定し、さらに **Grove Base HAT** 経由で **M5Stack ENV IV Unit (SHT40 + BMP280)** から室温・湿度・気圧を取得してWinSV (Goサーバー) に自動送信するPythonロジックです。

---

## 🔌 ハードウェア配線図

### 1. 環境センサー (M5Stack ENV IV ↔ Grove Base HAT)
付属のGroveケーブル（HY2.0-4P）で Grove Base HAT の **I2C ポート** に接続します。
- **Sensirion SHT40** (温度・湿度): I2C アドレス `0x44`
- **Bosch BMP280** (気圧): I2C アドレス `0x76`

### 2. ロードセル ↔ HX711 モジュール
ロードセルのリード線（4線式）をHX711の端子台に接続します。
| ロードセル配線色 | HX711 端子 | 説明 |
| :--- | :--- | :--- |
| **赤 (Red)** | `E+` (Excitation+) | 電源供給 (+) |
| **黒 (Black)** | `E-` (Excitation-) | グランド (-) |
| **白 (White)** | `A-` (Signal-) | 信号 (-) |
| **緑 (Green)** | `A+` (Signal+) | 信号 (+) |

*(※ シールド線(黄/透明)がある場合は `GND` または `SHIELD` へ接続)*

### 3. HX711 ↔ Raspberry Pi (または Grove HAT) GPIO
| HX711 ピン | Raspberry Pi ピン | 備考 |
| :--- | :--- | :--- |
| `VCC` | `5V` (Pin 2 or 4) | または 3.3V (HX711モジュール仕様による) |
| `GND` | `GND` (Pin 6 or 9) | 共通グランド |
| `DT` (Data) | `GPIO 5` (Pin 29 / Grove D5) | `config.json` で変更可能 |
| `SCK` (Clock) | `GPIO 6` (Pin 31 / Grove D6) | `config.json` で変更可能 |


---

## 📦 セットアップ手順

### 1. 依存ライブラリのインストール
```bash
sudo apt update
sudo apt install -y python3-pip python3-rpi.gpio
pip3 install -r requirements.txt
```

### 2. キャリブレーション (校正)
天板や皿を取り付けた状態で校正スクリプトを実行します。
```bash
python3 calibrate.py
```
1. ゼロ点合わせ（何も乗せずに Enter）
2. 既知の重り（例: 500gのペットボトル）を乗せて重さ(g)を入力
3. 計算された校正値が `config.json` に自動保存されます。

---

## ⚙️ 設定 (`config.json`)

```json
{
  "server_url": "http://192.168.1.100:8080",  // WinSVのIPアドレスとポート
  "device_id": "raspi-cat-scale-01",          // デバイス固有ID
  "device_type": "scale",                     // "scale" (体重計) または "feeder" (給餌器)
  "mode": "scale",                            // "scale" または "feeder"
  "pin_dout": 5,                              // HX711 DT ピン (BCM)
  "pin_pd_sck": 6,                            // HX711 SCK ピン (BCM)
  "scale_threshold_g": 500.0,                 // 猫が乗ったと判定する閾値(g)
  "feeder_change_threshold_g": 3.0            // 食事/補充とみなす重量変化(g)
}
```

---

## 🏃 実行

### テスト実行
```bash
python3 measure_service.py
```

### systemdによる自動常駐化 (OS起動時自動スタート)
```bash
sudo cp cat_logger.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable cat_logger.service
sudo systemctl start cat_logger.service

# 動作ログの確認
journalctl -u cat_logger.service -f
```

---

## 💡 特徴・安心設計
- **オフラインバッファ**: WinSVが再起動中やWiFi切断時でも、測定データをローカル（`offline_queue.json`）に一時保存し、復帰時に自動でまとめて再送します。
- **ノイズフィルタリング**: メディアン（中央値）フィルタと安定判定アルゴリズムにより、猫が動いている間の揺れノイズを排除して正確な体重・食事量を確定します。
- **モックモード対応**: PC上でもテスト実行できるように、RPi.GPIOがない環境では自動でシミュレーションモードで動作します。
