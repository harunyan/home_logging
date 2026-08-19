# 🐾 猫餌ログ & 猫体重計 & 環境温湿度 システム仕様書 (Cat Home Logging System)

---

## 1. システム概要

### 1.1 目的・背景
本システムは、飼い猫の健康管理（体重推移、食事量、食事回数、食事時刻）および飼育環境管理（室温・湿度・気圧）を日常の負担なく自動で記録・可視化することを目的としたIoTホームロギングシステムです。

市販のペット用スマート機器やクラウドサービスに依存せず、オープンな構成（Raspberry Pi + ロードセル + Grove HAT + M5Stack ENV IV + Windows 自宅サーバー）により、プライバシーを保護しつつ柔軟な拡張・カスタマイズが可能な構成を実現します。

### 1.2 システムの特徴
- **エッジ測定（Raspberry Pi + HX711 + M5Stack ENV IV）**: 
  - ロードセルによる高精度な重量計測とエッジ側でのリアルタイムイベント判定（体重確定、食事量算出、フード補充検知）。
  - **Grove Base HAT** を介して **M5Stack ENV IV (SHT40 + BMP280)** をI2C接続し、高精度な室温・湿度・気圧を自動定期ロギング。
- **完全スタンドアロンな集計基盤（Windows Server + Go）**: 外部クラウド不要、CGO不要、単一バイナリで動作する堅牢・軽量なGo製サーバー。
- **耐障害性（オフラインキューイング）**: 自宅サーバーの再起動時やWi-Fi切断時でも、Raspberry Pi内部にデータを蓄積し、サーバー復帰時に自動で一括再送。
- **内蔵Webダッシュボード**: ブラウザを開くだけで、本日の食事回数・合計量、最新体重、最新室温・湿度、各デバイスの稼働状態をリアルタイム表示。

---

## 2. システムアーキテクチャ

### 2.1 全体構成図

```mermaid
flowchart TD
    subgraph EdgeDevice ["Raspberry Pi 測定ユニット (複数設置可能)"]
        subgraph WeightSensors ["重量測定系"]
            LC["ロードセル (歪みゲージ)"] -->|アナログ微小電圧| ADC["HX711 24bit ADC"]
            ADC -->|GPIO bit-bang| PyCore["Python 測定サービス\n(measure_service.py)"]
        end

        subgraph EnvSensors ["環境測定系"]
            GroveHAT["Grove Base HAT for Raspberry Pi"]
            EnvIV["M5Stack ENV IV Unit\n(SHT40: 温湿度 / BMP280: 気圧)"] -->|I2C通信 (HY2.0-4P)| GroveHAT
            GroveHAT -->|/dev/i2c-1| PyCore
        end

        PyCore --> Filter["外れ値除去 & 安定判定 & 環境サンプリング"]
        Filter --> Mode{"イベント種別判定"}
        Mode -->|scale モード| EventScale["体重確定イベント"]
        Mode -->|feeder モード| EventFeeder["食事完了 / 補充イベント"]
        Mode -->|定期環境測定| EventEnv["環境温湿度イベント"]

        EventScale --> Sender["WinSV 送信モジュール"]
        EventFeeder --> Sender
        EventEnv --> Sender
        Sender -->|オフライン時| OfflineQueue[("ローカルバッファ\noffline_queue.json")]
        OfflineQueue -.->|復帰時再送| Sender
    end

    Sender ==>|HTTP POST /api/v1/events (JSON)| WinSV

    subgraph WinSV ["Windows 自宅サーバー (WinSV)"]
        GoServer["Go 言語 受信・集計サーバー (server_go)"]
        GoServer -->|追記保存| JSONL[("永続ログ\ndata/events.jsonl")]
        GoServer --> MemCache[("オンメモリキャッシュ\n(最新5,000件)")]
        GoServer --> Aggregator["日次サマリー・温湿度集計・死活監視"]
        GoServer --> EmbedWeb["内蔵 Web サーバー (HTML/JS/CSS)"]
    end

    subgraph Client ["ブラウザ・クライアント"]
        Browser["PC / スマホ ブラウザ\n(http://<WinSV_IP>:8080)"] <--> EmbedWeb
    end
```

---

## 3. ハードウェア仕様・配線要件

### 3.1 部品一覧
| 部品名 | 推奨仕様・型番 | 用途 | 数量 | 接続方式 |
| :--- | :--- | :--- | :--- | :--- |
| **Raspberry Pi** | Zero 2 W / 3B / 4B / 5 | センサー制御・データ中継 | 1台〜 | - |
| **Grove Base HAT** | Seeed Studio Grove Base HAT for Raspberry Pi | Groveコネクタ拡張・I2Cポート提供 | 1個 | 40pin GPIOスタック |
| **環境センサー** | **M5Stack Unit ENV IV** (SHT40 + BMP280) | 高精度 室温(℃)・湿度(%)・気圧(hPa) 測定 | 1個 | Grove I2Cポート |
| **ADコンバータ** | HX711 (24bit Load Cell ADC) | ロードセル微小電圧信号の増幅・AD変換 | 1〜2個 | GPIO (DT/SCK) |
| **ロードセル (体重計用)** | 4線式 5kg〜10kg (または3線式ハーフブリッジ×4構成) | 猫の体重測定（スケール天板下） | 1組 | HX711 端子台 |
| **ロードセル (給餌器用)** | 4線式 500g〜1kg | 猫の餌皿・残量測定 | 1組 | HX711 端子台 |
| **天板 / 皿台座** | アクリル板、MDF板、3Dプリント皿受け等 | 荷重をロードセルへ均等伝達 | 1式 | - |

---

### 3.2 環境センサー配線 (M5Stack ENV IV ↔ Grove Base HAT)
M5Stack ENV IV Unit を付属の Grove ケーブル（HY2.0-4P）で Grove Base HAT の **I2C ポート** に接続します。

| 信号線 | ケーブル色 | 機能 | 接続先 | I2C アドレス |
| :--- | :--- | :--- | :--- | :--- |
| **SCL** | 黄 (Yellow) | I2C クロック | Grove Base HAT I2C ポート (SCL / BCM 3) | - |
| **SDA** | 白 (White) | I2C データ | Grove Base HAT I2C ポート (SDA / BCM 2) | - |
| **VCC** | 赤 (Red) | 電源 (3.3V) | Grove Base HAT VCC (3.3V) | - |
| **GND** | 黒 (Black) | グランド | Grove Base HAT GND | - |

- **搭載センサーICとI2Cアドレス**:
  - **Sensirion SHT40** (高精度温度・湿度センサ): `0x44`
    - 温度測定精度: ±0.2℃
    - 湿度測定精度: ±1.8% RH
  - **Bosch BMP280** (絶対気圧センサ): `0x76` (または `0x77`)
    - 気圧測定精度: ±1 hPa (標高・気圧変化計測)

---

### 3.3 ロードセル ↔ HX711 配線
ロードセルのリード線（4線式ホイートストンブリッジ）をHX711の端子台に接続します。

| ロードセル配線色 | HX711 端子 | 信号名 | 説明 |
| :--- | :--- | :--- | :--- |
| **赤 (Red)** | `E+` | Excitation + | 励起電源 (+) |
| **黒 (Black)** | `E-` | Excitation - | 励起グランド (-) |
| **白 (White)** | `A-` | Signal A - | 差動入力 (-) |
| **緑 (Green)** | `A+` | Signal A + | 差動入力 (+) |
| *(シールド)* | `GND` / `SHIELD` | Shield | ノイズシールド（ある場合） |

---

### 3.4 HX711 ↔ Raspberry Pi (または Grove HAT) GPIO 配線
Grove Base HATの上部ピンヘッダ、またはデジタルポート（D5/D6）から接続可能です。

| HX711 ピン | Raspberry Pi / HAT ピン | GPIO 番号 (BCM) | 備考 |
| :--- | :--- | :--- | :--- |
| `VCC` | Pin 2 または Pin 4 | - | 5V 電源（または3.3V） |
| `GND` | Pin 6 または Pin 9 | - | 共通グランド |
| `DT` (Data) | Pin 29 / Grove D5 | `GPIO 5` | データ入力（`config.json`で変更可能） |
| `SCK` (Clock) | Pin 31 / Grove D6 | `GPIO 6` | クロック出力（`config.json`で変更可能） |

---

## 4. Raspberry Pi 側 (Python エッジ処理) 仕様

### 4.1 測定ロジックと動作モード

#### A. 猫体重計モード (`scale`)
1. **待機状態**: 常時 0.5 秒間隔でサンプリング。
2. **乗車検知**: 測定値が `scale_threshold_g`（デフォルト: 500g）を超えた場合、猫が乗ったと判定してサンプリングを開始。
3. **サンプリング**: 猫が乗っている間、直近最大20件の測定値をメモリバッファに保持。
4. **降車検知・重量確定**: 測定値が閾値の70%を下回った瞬間に降車と判定。
   - サンプル数が5件以上ある場合、上下の極値（飛び値ノイズ）をトリミングした上で中央平均値を計算し、確定体重としてWinSVへ送信。
   - サンプル数が少なすぎる場合（一瞬踏んだだけなど）は誤検知として破棄。

#### B. 猫餌皿モード (`feeder`)
1. **初期ベースライン測定**: 起動時に10回平均で基準重量（空皿＋既存フードの重さ）を取得。
2. **重量変動監視**: 1秒間隔で現在重量を測定し、ベースラインとの差分 `delta` を監視。
3. **イベント判定**:
   - `delta <= -feeder_change_threshold_g` (減少: 3g以上): 猫が食事を終了したと判定。`meal_finished` イベント（喫食量、残量）を送信し、ベースラインを現在の重量に更新。
   - `delta >= +feeder_change_threshold_g` (増加: 3g以上): 人間または自動給餌器によるフード補充と判定。`refill` イベント（補充量、総量）を送信し、ベースラインを更新。
4. **定期死活監視 (`periodic_ping`)**: 変化がなくても5分ごとに現在の残量をWinSVへ通知。

#### C. 環境温湿度・気圧監視 (M5Stack ENV IV 連携)
1. **定期サンプリング**: 1分〜5分間隔（設定可能）で I2C 経由で SHT40 / BMP280 からデータを取得。
2. **測定項目**:
   - 室温: `temperature_c` (℃)
   - 相対湿度: `humidity_pct` (%)
   - 気圧: `pressure_hpa` (hPa)
3. **イベント送信**: `event_type = "env_measured"` としてWinSVへ送信。
4. **複合通知**: 体重測定 (`weight_measured`) や食事完了 (`meal_finished`) イベント発生時にも、その瞬間の環境温湿度データを付与して送信可能。

### 4.2 キャリブレーション (校正) 仕様 (`calibrate.py`)
天板や皿を載せた状態で、以下を対話式に実行：
1. **ゼロ点（風袋引き）取得**: 無負荷状態で `offset`（ADC生値）を測定。
2. **スパン校正**: 既知の重り（例: 500gのボトルなど）を載せ、`reference_unit = (生値 - offset) / 実重量(g)` を算出。
3. 計算結果を `config.json` に即座に保存。

### 4.3 オフライン耐障害性 (`offline_queue.json`)
- 送信失敗（WinSV停止、LAN障害、Wi-Fi切断）時は、ローカルの `offline_queue.json` にイベントを追記保存。
- 通信回復時に、蓄積された全イベントをJSON配列としてWinSVへ一括POSTし、完了後にローカルキューをクリア。

### 4.4 自動常駐化 (`systemd`)
`cat_logger.service` によりOS起動時にバックグラウンドで自動起動し、クラッシュ時も自動再起動（`Restart=always`, `RestartSec=5`）。

---

## 5. Windows Server 側 (Go バックエンド & WebUI) 仕様

### 5.1 構成と設計思想
- **依存ゼロ**: Go標準パッケージのみで構築（CGO不要、外部依存ゼロ）。
- **データ永続化**: JSON Lines 形式（`data/events.jsonl`）。
- **高速性**: 直近5,000件のオンメモリキャッシュ保持により、高速レスポンスを実現。

### 5.2 REST API インターフェース仕様

#### 1. 信号受信: `POST /api/v1/events`
単一イベント、または一括再送用のイベント配列を受信。

- **リクエスト例 (環境温湿度イベント)**:
```json
{
  "device_id": "raspi-env-01",
  "device_type": "env_sensor",
  "event_type": "env_measured",
  "temperature_c": 24.8,
  "humidity_pct": 52.3,
  "pressure_hpa": 1013.25,
  "note": "M5Stack ENV IV (Grove I2C)",
  "timestamp": "2026-08-19T12:00:00Z"
}
```

- **リクエスト例 (猫食事完了 + 環境情報付与)**:
```json
{
  "device_id": "raspi-feeder-01",
  "device_type": "feeder",
  "event_type": "meal_finished",
  "weight_g": 32.5,
  "delta_g": -12.5,
  "temperature_c": 25.1,
  "humidity_pct": 51.8,
  "note": "喫食量: 12.5g",
  "timestamp": "2026-08-19T12:05:00Z"
}
```

- **レスポンス**: `201 Created`
```json
{
  "status": "success",
  "saved": 1
}
```

#### 2. ログ取得: `GET /api/v1/events`
- クエリパラメータ: `?limit=50&device_id=raspi-env-01&event_type=env_measured`

#### 3. デバイス一覧・死活状態: `GET /api/v1/devices`
- 各デバイスのオンライン状態、最終受信値（体重/残量/温湿度）を返却。

#### 4. 本日のサマリー集計: `GET /api/v1/summary`
- **レスポンス**: `200 OK`
```json
{
  "total_events_today": 28,
  "today_meals_count": 4,
  "today_food_eaten_g": 48.5,
  "latest_cat_weight_g": 4350.2,
  "latest_weight_time": "2026-08-19T11:45:00Z",
  "latest_temperature_c": 24.8,
  "latest_humidity_pct": 52.3,
  "latest_pressure_hpa": 1013.2,
  "latest_env_time": "2026-08-19T12:00:00Z",
  "active_devices_count": 2
}
```

#### 5. ヘルスチェック: `GET /health`

---

## 6. データモデル定義

### 6.1 `LogEvent` (測定・通知イベント)
| フィールド | 型 | 必須 | 説明 | 例 |
| :--- | :--- | :---: | :--- | :--- |
| `id` | string | - | イベント一意ID (空の場合は自動生成) | `"1755580000-raspi-01"` |
| `device_id` | string | ○ | 送信元デバイス識別子 | `"raspi-feeder-01"` |
| `device_type`| string | ○ | 分類 (`"scale"`, `"feeder"`, `"env_sensor"`, `"sensor"`) | `"feeder"` |
| `event_type` | string | ○ | 種別 (`"weight_measured"`, `"meal_finished"`, `"refill"`, `"env_measured"`, `"periodic_ping"`) | `"meal_finished"` |
| `weight_g` | float64| - | 測定重量 (g) | `32.4` |
| `delta_g` | *float64| - | 変動重量 (g) (喫食時は負数、補充時は正数) | `-12.6` |
| `temperature_c` | *float64| - | **室温 (℃)** (M5Stack ENV IV SHT40) | `24.8` |
| `humidity_pct` | *float64| - | **相対湿度 (%)** (M5Stack ENV IV SHT40) | `52.3` |
| `pressure_hpa` | *float64| - | **気圧 (hPa)** (M5Stack ENV IV BMP280) | `1013.25` |
| `raw_value` | *int64 | - | HX711のADC生値（デバッグ用） | `8412300` |
| `note` | string | - | 付加情報・メモ | `"喫食量: 12.6g / 室温24.8℃"` |
| `timestamp` | time | ○ | デバイス側での発生日時 (ISO 8601) | `"2026-08-19T12:00:00Z"` |
| `received_at`| time | - | サーバー側受信日時 | `"2026-08-19T12:00:01Z"` |

---

## 7. Webダッシュボード仕様

Windows Server上のGoサーバー内蔵WebUI（`http://<WinSV_IP>:8080/`）で提供される機能：

1. **KPIサマリーカード**:
   - **今日の食事**: 回数 & 合計食事量 (g)
   - **最新体重**: 猫の測定体重 (kg / g) と測定時刻
   - **室温・湿度 (ENV IV)**: 現在の室温 (℃) / 湿度 (%) / 気圧 (hPa)（快適度インジケーター表示）
   - **システム状態**: 接続デバイス台数 & オンラインバッジ
2. **デバイスステータス一覧**:
   - 各Raspberry Piの最新受信時刻、現在値、通信状態（オンライン/オフライン）
3. **イベントタイムライン**:
   - 食事完了、体重測定、補充、環境温湿度ログのリアルタイム一覧
4. **自動更新**:
   - 5秒ごとの自動ポーリングで常時最新化

---

## 8. 今後の拡張・ロードマップ案

1. **温湿度連動アラート**:
   - 夏季の熱中症予防（室温28℃以上・湿度70%以上）や冬季の乾燥対策アラート通知。
2. **多頭飼い対応 (個体識別)**:
   - 体重範囲による自動猫判定、RFIDタグ首輪リーダー連携。
3. **猫トイレログ (排泄・滞在監視)**:
   - トイレ下ロードセルによる排泄回数・滞在時間モニタリング。
4. **長期データ分析・グラフ化**:
   - 体重・食事量・室温湿度の相関グラフ表示（季節変化による食欲分析など）。
