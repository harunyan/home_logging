# ☁️ XREA 展開ガイド (https://veris.jp/home_logging/)

XREA レンタルサーバー上に **Cat Home Logging Webサービス** を展開・ホストするための手順書です。

---

## 📁 フォルダ構成

XREA の `public_html/home_logging/` 配下に、本 `web_xrea` フォルダの中身をそのままアップロードします：

```text
public_html/
└── home_logging/
    ├── index.html          # 紺色ベースの時系列グラフWebダッシュボード
    ├── .htaccess           # データベース保護 & CORS設定
    ├── api/
    │   ├── config.php      # 共通設定・SQLite制御・AES-256-GCM自動復号
    │   ├── db_write.php    # データ受信API (WinSV / ラズパイから暗号化POST)
    │   ├── get_sensor.php  # グラフ描画用データ出力API
    │   └── pubkey.php      # 公開鍵・ステータス確認API
    └── data/               # SQLiteデータベース保存先 (自動生成 / 777権限)
```

---

## 🚀 アップロード＆設定手順

### 1. XREA へのファイル配置
FTPソフト（FileZilla等）または XREA のファイルマネージャーで：
- XREA の `public_html/` 直下に **`home_logging`** フォルダを作成。
- その中に `web_xrea/` の中身（`index.html`, `.htaccess`, `api/` フォルダ）をすべてアップロードします。

### 2. `data/` フォルダのパーミッション設定
SQLite データベースを書き込めるようにパーミッションを設定します：
- `public_html/home_logging/data/` フォルダのパーミッションを **`777` (または `707` / `755`)** に設定します。

---

## 📡 WinSV (ion3) からの自動中継（暗号化リレー）の設定

WinSV（`ion3`）がラズパイから受信したデータを、**自動的に AES-256-GCM で暗号化して XREA へ中継送信** させるには、起動時に `-relay-url` を指定します：

```powershell
.\home_logging_server.exe -port 8080 -relay-url https://veris.jp/home_logging/api/db_write.php
```

`start_server.bat` を使っている場合は、バットファイルを以下のように編集します：
```bat
@echo off
cd /d %~dp0
home_logging_server.exe -port 8080 -data data/events.jsonl -relay-url https://veris.jp/home_logging/api/db_write.php
pause
```

---

## 🌐 動作確認

1. **APIの動作確認**:
   - ブラウザで `https://veris.jp/home_logging/api/pubkey.php` にアクセス
   - `{"status":"ok","service":"cat-home-logging-xrea",...}` と表示されればOKです。
2. **Webダッシュボードの確認**:
   - ブラウザで **`https://veris.jp/home_logging/`** にアクセス
   - 紺色ベースの時系列グラフ（餌皿残量・室温・湿度・気圧）がリアルタイムに表示されます！
