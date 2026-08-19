# 🚀 新規環境セットアップ & コード理解ガイド (SETUP_GUIDE.md)

このドキュメントは、新しいPC環境やRaspberry Pi実機に本リポジトリを展開した際、**「コード構成の全体像を把握し、即座に動作確認を行う」** ための実践ガイドです。

---

## 1. 📁 コード構成と各モジュールの役割

```text
home_logging/
├── SPECIFICATION.md          # 🐾 システム全体設計・詳細機能仕様書
├── SETUP_GUIDE.md            # 🚀 新規環境セットアップ手順書 (本ファイル)
├── README.md                 # プロジェクト概要
├── .gitignore                # Git除外設定 (ログ、キャッシュ、ローカル設定等)
├── .gitattributes            # 改行コード正規化設定
│
├── server_go/                # 【WinSV用】Go言語 信号受信サーバー & WebUI
│   ├── main.go               # エントリーポイント / ルーティング / 静的ファイル配信
│   ├── models/models.go      # イベントデータ・集計構造体の定義
│   ├── handlers/handlers.go  # HTTP APIハンドラー (POST受信 / GET取得)
│   ├── storage/storage.go    # JSONL永続化 & オンメモリ集計ロジック
│   ├── static/index.html     # Webダッシュボード (HTML/CSS/JS)
│   ├── start_server.bat      # Windows用ワンクリック起動バッチ
│   └── build_windows.bat     # Windows用単一実行ファイルビルドバッチ
│
├── sensor_raspi/             # 【Raspberry Pi用】センサー測定 & 送信モジュール
│   ├── hx711.py              # HX711 24bit ADコンバータ制御ドライバ (Mock対応)
│   ├── env_sensor.py         # M5Stack ENV IV (SHT40+BMP280) I2Cリーダー (Mock対応)
│   ├── calibrate.py          # 対話型ロードセル校正・係数算出ツール
│   ├── measure_service.py    # メイン測定常駐デーモン (オフラインキュー・ノイズ除去)
│   ├── config.json.example   # 設定ファイルのテンプレート
│   ├── requirements.txt      # Python依存ライブラリ (RPi.GPIO, smbus2)
│   └── cat_logger.service    # systemd 自動起動Unitファイル
│
└── scripts/
    └── simulate_client.py    # 開発PC用 センサー信号シミュレータ (テストデータ投入用)
```

---

## 2. 💻 PC単体でのクイック動作確認 (シミュレーション動作)

実機（Raspberry Pi）が手元にない開発環境でも、PC単体でGoサーバーを起動し、Pythonシミュレータからテストデータを投入して動作を確認できます。

### ステップ 1: Goサーバーの起動
```powershell
cd server_go

# Goがインストールされている場合
go run main.go -port 8080

# またはビルド済みexeがある場合は start_server.bat を実行
```
サーバーが起動すると、`http://localhost:8080` でWebダッシュボードが開きます。

### ステップ 2: シミュレータからテストデータを送信
別ターミナルを開き、リポジトリ直下のシミュレータを実行します（Python標準ライブラリのみで動作）：

```powershell
# 1回だけ全イベント（体重測定、食事完了、フード補充、温湿度）を送信
python scripts/simulate_client.py

# または 3秒間隔でランダムなイベントを連続送信
python scripts/simulate_client.py --continuous --interval 3.0
```

### ステップ 3: ダッシュボードの確認
ブラウザで `http://localhost:8080` を開くと、リアルタイムにデータが反映されることが確認できます：
- **猫の測定体重**: 最新の体重（例: 4.3kg）
- **食事回数 & 食べた量**: 日次集計
- **室内環境 (ENV IV)**: 室温 (℃) / 湿度 (%) / 気圧 (hPa)
- **デバイス一覧 & 受信ログテーブル**

---

## 3. 🍓 Raspberry Pi 実機へのセットアップ手順

### ステップ 1: ハードウェアの接続
1. **Grove Base HAT** を Raspberry Pi の 40ピン GPIO にスタックします。
2. **M5Stack Unit ENV IV** を Grove ケーブルで HAT の **I2C ポート** に接続します。
3. **ロードセル & HX711**:
   - ロードセル 4線を HX711 端子台（`E+`, `E-`, `A-`, `A+`）に接続。
   - HX711の `DT` を `GPIO 5`、`SCK` を `GPIO 6`、`VCC` を `5V`、`GND` を `GND` に接続。

### ステップ 2: Raspberry Pi での I2C 有効化
```bash
sudo raspi-config
# [3 Interface Options] -> [I4 I2C] -> [Yes] を選択して再起動
```

### ステップ 3: 依存パッケージのインストール
```bash
cd sensor_raspi
sudo apt update
sudo apt install -y python3-pip python3-smbus i2c-tools
pip3 install -r requirements.txt

# I2Cアドレスの確認 (0x44: SHT40, 0x76: BMP280 が見えればOK)
i2cdetect -y 1
```

### ステップ 4: 設定ファイルの作成
```bash
cp config.json.example config.json
nano config.json
```
`config.json` 内の `server_url` を、Windows Server (WinSV) のIPアドレス（例: `http://192.168.1.50:8080`）に書き換えます。

### ステップ 5: ロードセルの校正 (キャリブレーション)
天板や餌皿を取り付けた状態で実行します：
```bash
python3 calibrate.py
```
- 何も載せずに Enter（ゼロ点調整）
- 重さが分かっている重り（例: 500gのペットボトル）を載せて、グラム数を入力して Enter
- 校正値が `config.json` に自動保存されます。

### ステップ 6: 測定サービスの起動
```bash
# フォアグラウンドでテスト実行
python3 measure_service.py

# systemdで常駐化 (OS起動時自動スタート)
sudo cp cat_logger.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable cat_logger.service
sudo systemctl start cat_logger.service

# ログ確認
journalctl -u cat_logger.service -f
```

---

## 4. 🛡️ Git管理のルールと注意点

### Git管理対象 (コミットするもの)
- すべてのソースコード（Go、Python、HTML/JS）
- ドキュメント（`SPECIFICATION.md`, `SETUP_GUIDE.md`, `README.md`）
- 設定テンプレート（`config.json.example`）
- テスト・シミュレータ（`scripts/simulate_client.py`）

### Git管理除外 (コミットしないもの - `.gitignore` で保護済み)
- `sensor_raspi/config.json`: 実機の固有IPや個体校正値が含まれるため除外
- `server_go/data/*.jsonl`: 稼働中に蓄積される実測ログデータ
- `sensor_raspi/offline_queue.json`: オフライン時に一時生成されるキュー
- `*.exe`, `__pycache__/`: ビルド成果物・中間ファイル
