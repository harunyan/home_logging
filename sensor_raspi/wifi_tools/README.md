# 📶 Raspberry Pi Wi-Fi 安定化 & 自動復旧ツール (wifi_tools)

Raspberry Pi を Wi-Fi 経由（SSH等）のみで運用している環境において、**「Wi-Fi切断による孤立・文鎮化を防ぎ、自律的に復旧させる」** ためのスクリプト群です。

---

## ⚠️ なぜ SSH での手動 `link down` は危険なのか？

SSH接続中に `sudo ip link set wlan0 down` や `sudo nmcli radio wifi off` を直接実行すると、**その瞬間にSSHセッションが遮断され、その後に続く `up` コマンドが実行されなくなります**。その結果、Wi-Fiが無効のまま放置され、ラズパイの電源を物理的に入れ直すしかなくなります。

本ツール群は、以下の2重の仕組みでこの問題を完全に回避します：

1. **自律型 Watchdog (`wifi_auto_reconnect.sh` + systemd timer)**:
   - 2分おきにルーター疎通をチェックし、切断されていれば自動でWi-Fiを再起動して復帰。
2. **安全手動リセット (`wifi_safe_reset.sh`)**:
   - `nohup` / サブシェルにより、SSHが切断されても「省電力OFF → Down → 待機 → Up → 再接続」をバックグラウンドで最後まで完遂。

---

## 📦 ファイル一覧

| ファイル | 役割 |
| :--- | :--- |
| **`install.sh`** | ワンコマンドで全スクリプトの配置・省電力OFF・自動監視を有効化するインストーラ |
| **`wifi_auto_reconnect.sh`** | ルーター疎通監視 & 自動再接続スクリプト |
| **`wifi_safe_reset.sh`** | SSH経由でも安全にWi-Fiを再起動・復帰させるコマンド |
| **`wifi_watchdog.service`** | systemd サービス定義 |
| **`wifi_watchdog.timer`** | 2分間隔で定期実行する systemd タイマー |

---

## 🚀 使い方

### 1. 一括インストール (推奨)
Raspberry Pi 上で以下を実行します：

```bash
cd sensor_raspi/wifi_tools
sudo chmod +x install.sh
sudo ./install.sh
```

これだけで以下がすべて自動設定されます：
- Wi-Fi省電力モード（Power Management）の恒久無効化
- 2分間隔の自動死活監視＆自律復旧タイマーの起動
- `/usr/local/bin/` へのコマンド配置

---

### 2. 手動で安全に Wi-Fi をリセットしたい場合
SSH接続中に手動でWi-Fiを再起動したいときは、以下のコマンドを実行します：

```bash
sudo wifi_safe_reset.sh
```
* コマンド実行後、バックグラウンドに切り替わり安全に再接続されます。
* 約10秒後に再度SSH接続が通るようになります。

---

### 3. ログ・動作状態の確認

```bash
# タイマーの稼働状況を確認
systemctl status wifi_watchdog.timer

# 自動復旧ログの確認
cat /var/log/wifi_watchdog.log

# journald ログの確認
journalctl -u wifi_watchdog.service -e
```
