# 🐾 Cat Home Logging System (猫餌ログ & 猫体重計 & 環境温湿度 計画)

Raspberry Pi（ロードセル + HX711 + Grove HAT + M5Stack ENV IV）で猫の体重・食事量および室温・湿度・気圧を測定し、Windows Server (WinSV) のGo製サーバーへ信号を送信してログ・集計・可視化を行うシステムです。

👉 **詳細な設計・アーキテクチャ・API・ハードウェア仕様は [SPECIFICATION.md](file:///C:/Source/gemini/home_logging/SPECIFICATION.md) をご覧ください。**

---

## 📁 ディレクトリ構成

```text
home_logging/
├── SPECIFICATION.md      # 🐾 システム全体設計・詳細機能仕様書
├── server_go/            # 【WinSV用】Go言語 信号受信サーバー & Webダッシュボード
│   ├── main.go           # サーバーエントリーポイント (embed WebUI対応)
│   ├── handlers/         # HTTP APIハンドラー (POST受信 / GET取得)
│   ├── models/           # ログイベント・温湿度・デバイス状態モデル定義
│   ├── storage/          # JSONL永続化 & オンメモリ集計ロジック
│   ├── static/           # リアルタイムWebモニタリング画面 (HTML/CSS/JS)
│   ├── start_server.bat  # Windows起動用バッチ
│   ├── build_windows.bat # Windows用バイナリビルド
│   └── README.md
│
└── sensor_raspi/         # 【Raspberry Pi用】HX711 & ENV IV 測定・送信モジュール
    ├── hx711.py          # HX711 24bit ADCドライバ (Mockモード対応)
    ├── env_sensor.py     # M5Stack ENV IV (SHT40+BMP280) I2Cリーダー
    ├── calibrate.py      # 対話型ロードセル校正・係数算出スクリプト
    ├── measure_service.py # 重量・温湿度監視 & WinSV送信デーモン (オフライン再送対応)
    ├── config.json       # ピン番号・校正値・I2C設定・サーバーURL設定
    ├── requirements.txt  # Python依存パッケージ (RPi.GPIO, smbus2)
    ├── cat_logger.service# systemd自動常駐用Unitファイル
    └── README.md
```

---

## 🚀 クイックスタート

### 1. WinSV (サーバー側) の起動
```powershell
cd server_go
go run main.go -port 8080
# または start_server.bat を実行
```
ブラウザで `http://localhost:8080` を開くと、リアルタイムダッシュボード（体重・食事量・室温湿度）が表示されます。

### 2. Raspberry Pi (センサー側) のセットアップ
```bash
cd sensor_raspi

# 依存関係インストール (RPi.GPIO, smbus2)
pip3 install -r requirements.txt

# ロードセルの校正 (ゼロ点合わせ & 既知の重り測定)
python3 calibrate.py

# 監視サービス起動 (重量 + M5Stack ENV IV 温湿度)
python3 measure_service.py
```

---

## 🌟 主な機能
- **リアルタイムWebダッシュボード**: 今日の食事回数・合計食事量、最新体重、最新室温・湿度・気圧、接続デバイスの稼働状態を表示。
- **高精度な環境測定 (M5Stack ENV IV)**: Grove Base HAT の I2C 経由で SHT40 (±0.2℃, ±1.8%RH) と BMP280 (気圧) を定期取得。
- **インテリジェントな重量イベント検知**:
  - `scale` モード: 猫が乗ったことを検知し、静止時の体重を正確にサンプリング（外れ値トリム平均）。
  - `feeder` モード: 食前後の差分から「食べた量」や「フード補充」を自動判別。
- **耐障害性**: WinSVがオフラインでも、Raspberry Pi内部にキューイングして復帰時に自動一括送信。

