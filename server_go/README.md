# WinSV 猫餌ログ＆猫体重計 信号受信サーバー (Go)

Raspberry Pi（ロードセル/HX711）から送信される重量測定信号・食事ログをリアルタイムで受信・保存・集計するGo言語製ミニマムサーバーです。

---

## 🌟 特徴
- **完全スタンドアロン**: Go標準ライブラリのみで実装（CGO不要、外部パッケージ依存ゼロ）。
- **Webダッシュボード内蔵**: `http://<WinSV_IP>:8080/` にアクセスするだけでリアルタイムモニタリングが可能。
- **データ永続化**: JSON Lines (`data/events.jsonl`) 形式で自動保存＆高速オンメモリ集計。
- **マルチデバイス対応**: 体重計・給餌器など複数台のRaspberry Piからの同時受信に対応。

---

## 🚀 起動方法 (Windows)

### 1. 直接実行 (Goがインストールされている場合)
```powershell
cd server_go
go run main.go -port 8080 -data data/events.jsonl
```

### 2. 単一バイナリ (.exe) としてビルド・常駐
```powershell
cd server_go
go build -ldflags "-s -w" -o home_logging_server.exe main.go
./home_logging_server.exe -port 8080
```
または `start_server.bat` をダブルクリックして起動できます。

---

## 📡 API 仕様

### 1. 信号受信 (POST `/api/v1/events`)
Raspberry Piから重量測定や食事完了イベントをPOSTします。

**リクエストボディ (JSON単体または配列)**:
```json
{
  "device_id": "raspi-scale-01",
  "device_type": "scale",
  "event_type": "weight_measured",
  "weight_g": 4350.2,
  "delta_g": null,
  "raw_value": 438120,
  "note": "安定測定",
  "timestamp": "2026-08-19T12:00:00+09:00"
}
```

**レスポンス**:
```json
{
  "status": "success",
  "saved": 1
}
```

### 2. ログ取得 (GET `/api/v1/events`)
- クエリパラメータ: `?limit=50&device_id=raspi-scale-01&event_type=weight_measured`

### 3. デバイス状態 (GET `/api/v1/devices`)
各クライアントのオンライン/オフライン状態、最終受信値を取得。

### 4. 日次サマリー (GET `/api/v1/summary`)
本日の食事回数・合計食事量、最新体重の集計を取得。

### 5. ヘルスチェック (GET `/health`)
`{"status":"ok","service":"cat-home-logging-winsv"}`
